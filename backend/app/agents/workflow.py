"""Bounded, observable, resumable investigation workflow built on LangGraph.

Graph (explicit state, no dynamic agent spawning, no cycles):

    START -> entry_router -> validate_incident -> triage -> retrieve_evidence -> diagnose
          -> plan_remediation -> governance_review -> policy_gate
          -> [awaiting approval: END] | execute_actions -> verify -> compose_report -> END
    (resume after approval enters directly at execute_actions)

Bounds: max steps, max tool calls, token budget, per-step and total deadlines, and
LangGraph's recursion limit. Every node emits persisted events; state is saved
after each node so runs survive restarts and never repeat completed actions.
"""

from __future__ import annotations

import json
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.agents.simulation import flatten_text, mark_incident
from app.agents.tools import MUTATING_ARGS, ToolBudgetExceeded, ToolContext, ToolExecutor
from app.ai.gateway import LLMResult, ModelGateway, ProviderError
from app.ai.prompts import PROMPTS
from app.core.config import Settings
from app.core.context import agent_var, investigation_id_var
from app.core.logging import get_logger
from app.db.base import utcnow
from app.domain import (
    RISK_ORDER,
    ActionStatus,
    IncidentStatus,
    InvestigationOutcome,
    InvestigationStatus,
    RiskLevel,
)
from app.models import ActionRecord, Evidence, Incident, InvestigationEvent, InvestigationRun, LLMCall
from app.policy.catalog import ACTION_CATALOG, PROHIBITED_ACTIONS
from app.policy.engine import POLICY_VERSION, Actor, PolicyEngine
from app.rag.injection import neutralize, wrap_untrusted
from app.rag.retrieval import Retriever
from app.services.actions import ActionService
from app.services.approvals import ApprovalService
from app.services.audit import record_audit
from app.services.flags import fault_enabled

log = get_logger("agents.workflow")
WORKFLOW_VERSION = "investigation-wf-1.4.0"

AGENTS: dict[str, str] = {
    "validate_incident": "Orchestrator",
    "triage": "Triage Agent",
    "retrieve_evidence": "Evidence Retrieval Agent",
    "diagnose": "Diagnostic Agent",
    "plan_remediation": "Remediation Planner Agent",
    "governance_review": "Governance/Risk Reviewer (advisory)",
    "policy_gate": "Policy Engine (deterministic)",
    "execute_actions": "Simulated Executor",
    "verify": "Verification Agent",
    "compose_report": "Final Report Composer",
}
ANALYSIS_NODES = ["validate_incident", "triage", "retrieve_evidence", "diagnose", "plan_remediation",
                  "governance_review", "policy_gate"]


class WFState(TypedDict, total=False):
    investigation_id: str
    phase: str
    step_count: int
    completed: list[str]
    incident: dict[str, Any]
    notes: str | None
    observations: dict[str, Any]
    observation_text: str
    triage: dict[str, Any]
    triage_source: str
    evidence: list[dict[str, Any]]
    retrieval: dict[str, Any]
    diagnosis: dict[str, Any]
    plan: dict[str, Any]
    plan_source: str
    plan_version: int
    governance: dict[str, Any]
    policy: dict[str, Any]
    execution: dict[str, Any]
    verification: dict[str, Any]
    report: dict[str, Any]
    outcome: str
    degraded_reasons: list[str]
    abort_reason: str | None
    sources: dict[str, str]


class WorkflowAbort(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class RunContext:
    db: Session
    run: InvestigationRun
    incident: Incident | None
    requester: Actor
    deadline: float
    tool_ctx: ToolContext
    tokens: int = 0
    tool_calls: int = 0
    degraded: list[str] = field(default_factory=list)

    @property
    def dry_run(self) -> bool:
        return self.run.execution_mode == "dry_run"


def diagnostic_calls(category: str, attrs: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Deterministic read-only diagnostic playbook per incident category (tool selection in code)."""
    if category == "statement_generation" and attrs.get("template_id"):
        return [("validate_synthetic_document_template", {"template_id": attrs["template_id"]})]
    if category == "kafka_consumer_lag":
        return [("inspect_synthetic_stream_metrics", {"stream": "cg-transaction-enricher"}),
                ("inspect_synthetic_stream_metrics", {"stream": "card-transactions"})]
    if category == "flink_job_failure":
        return [("inspect_synthetic_stream_metrics", {"stream": "flink-risk-aggregator"}),
                ("validate_synthetic_schema_compatibility", {"subject": "risk-events-value",
                                                             "writer_version": int(attrs.get("writer_version", 7)),
                                                             "reader_version": int(attrs.get("reader_version", 6))})]
    if category == "mq_queue_backlog":
        return [("inspect_synthetic_queue_metrics", {"queue_name": "PAYMENT.SETTLEMENT.IN"}),
                ("inspect_synthetic_queue_metrics", {"queue_name": "PAYMENT.SETTLEMENT.DLQ"})]
    if category == "duplicate_events":
        return [("inspect_synthetic_stream_metrics", {"stream": "payments-events"})]
    return []


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


class InvestigationWorkflow:
    def __init__(
        self,
        *,
        settings: Settings,
        gateway: ModelGateway,
        retriever: Retriever,
        tools: ToolExecutor,
        actions: ActionService,
        approvals: ApprovalService,
        policy: PolicyEngine,
    ) -> None:
        self.settings = settings
        self.gateway = gateway
        self.retriever = retriever
        self.tools = tools
        self.actions = actions
        self.approvals = approvals
        self.policy = policy

    # ================================================================= plumbing
    def _emit(self, rc: RunContext, event_type: str, status: str, message: str, *, agent: str | None = None,
              tool: str | None = None, payload: dict[str, Any] | None = None, duration_ms: int | None = None) -> None:
        rc.run.event_seq = (rc.run.event_seq or 0) + 1
        rc.db.add(InvestigationEvent(
            investigation_id=rc.run.id, seq=rc.run.event_seq, event_type=event_type, agent=agent, tool=tool,
            status=status, message=message[:2000], payload=_json_safe(payload or {}), duration_ms=duration_ms,
        ))
        rc.db.commit()

    def _persist(self, rc: RunContext, state: dict[str, Any], node: str) -> None:
        run = rc.run
        run.state = _json_safe({k: v for k, v in state.items()})
        run.current_node = node
        run.phase = state.get("phase", run.phase)
        run.step_count = int(state.get("step_count", run.step_count))
        run.tool_call_count = rc.tool_calls
        run.degraded = bool(rc.degraded)
        diag = state.get("diagnosis") or {}
        hyps = diag.get("hypotheses") or []
        run.confidence = hyps[0]["confidence"] if hyps and not diag.get("abstained") else None
        rc.db.commit()

    def _budget(self, rc: RunContext) -> None:
        rc.tool_calls += 1
        if rc.tool_calls > self.settings.workflow_max_tool_calls:
            raise ToolBudgetExceeded()

    def _tool(self, rc: RunContext, name: str, args: dict[str, Any]) -> dict[str, Any] | None:
        res = self.tools.invoke(rc.tool_ctx, name, args, incident=rc.incident)
        self._emit(rc, "tool_call", res.status, f"{name}: {res.message if not res.ok else 'ok'}",
                   agent=rc.tool_ctx.agent, tool=name,
                   payload={"args": args, "error_code": res.error_code, "tool_call_id": res.tool_call_id},
                   duration_ms=res.duration_ms)
        if not res.ok:
            reason = f"tool_error:{name}:{res.error_code}"
            if reason not in rc.degraded:
                rc.degraded.append(reason)
            return None
        return res.data

    def _llm(self, rc: RunContext, prompt_id: str, context_text: str, context: dict[str, Any]) -> LLMResult:
        prompt = PROMPTS[prompt_id]
        agent = rc.tool_ctx.agent or prompt_id
        started = time.perf_counter()
        try:
            result = self.gateway.generate(
                prompt,
                context_text=context_text,
                context=context,
                budget_remaining=self.settings.workflow_token_budget - rc.tokens,
                fault_provider_timeout=fault_enabled(rc.db, "provider_timeout"),
            )
        except ProviderError as exc:
            rc.db.add(LLMCall(
                tenant_id=rc.run.tenant_id, investigation_id=rc.run.id, agent=agent, provider=self.gateway.provider.name,
                model=self.gateway.provider.model, prompt_id=prompt.prompt_id, prompt_version=prompt.version,
                status="skipped" if exc.code in ("token_budget_exceeded", "circuit_open") else "error",
                error_code=exc.code, latency_ms=int((time.perf_counter() - started) * 1000),
                is_mock=self.gateway.provider.is_mock,
            ))
            self._emit(rc, "llm_call", "error", f"{prompt_id} v{prompt.version}: provider error {exc.code}",
                       agent=agent, payload={"error_code": exc.code, "prompt_id": prompt_id})
            rc.degraded.append(f"llm_unavailable:{prompt_id}:{exc.code}")
            if exc.code == "token_budget_exceeded":
                raise WorkflowAbort(exc.code) from exc
            raise
        rc.tokens += result.input_tokens + result.output_tokens
        rc.run.input_tokens = (rc.run.input_tokens or 0) + result.input_tokens
        rc.run.output_tokens = (rc.run.output_tokens or 0) + result.output_tokens
        rc.run.estimated_cost_usd = round((rc.run.estimated_cost_usd or 0.0) + result.estimated_cost_usd, 6)
        rc.db.add(LLMCall(
            tenant_id=rc.run.tenant_id, investigation_id=rc.run.id, agent=agent, provider=result.provider,
            model=result.model, prompt_id=result.prompt_id, prompt_version=result.prompt_version, status="ok",
            latency_ms=result.latency_ms, input_tokens=result.input_tokens, output_tokens=result.output_tokens,
            tokens_estimated=result.tokens_estimated, estimated_cost_usd=result.estimated_cost_usd,
            is_mock=result.is_mock, attempts=result.attempts,
        ))
        self._emit(rc, "llm_call", "ok",
                   f"{prompt_id} v{prompt.version} via {result.provider}/{result.model}"
                   + (" [MOCK MODE]" if result.is_mock else ""),
                   agent=agent, duration_ms=result.latency_ms,
                   payload={"prompt_id": prompt_id, "prompt_version": prompt.version, "input_tokens": result.input_tokens,
                            "output_tokens": result.output_tokens, "tokens_estimated": result.tokens_estimated,
                            "estimated_cost_usd": result.estimated_cost_usd, "is_mock": result.is_mock})
        if rc.tokens > self.settings.workflow_token_budget:
            raise WorkflowAbort("token_budget_exceeded")
        return result

    def _source(self, result: LLMResult | None) -> str:
        if result is None:
            return "deterministic"
        return "mock" if result.is_mock else "live_model"

    # ==================================================================== nodes
    def _validate_incident(self, rc: RunContext, state: WFState) -> dict[str, Any]:
        inc = rc.incident
        if inc is None or inc.tenant_id != rc.requester.tenant_id:
            raise WorkflowAbort("incident_not_found")
        if not self.policy.can_read_classification(rc.requester.role, inc.classification):
            raise WorkflowAbort("incident_not_authorized")
        data = self._tool(rc, "get_incident_details", {"incident_id": inc.id})
        if data is None:
            raise WorkflowAbort("incident_details_unavailable")
        if not rc.dry_run and inc.status == IncidentStatus.OPEN.value:
            mark_incident(rc.db, inc, IncidentStatus.INVESTIGATING,
                          f"AI investigation {rc.run.id[:8]} started by {rc.requester.username}.", source="bankops-ai")
            rc.db.commit()
        return {"incident": {**data, "attributes": inc.attributes or {}},
                "observations": {"incident_attributes": inc.attributes or {}}}

    def _triage(self, rc: RunContext, state: WFState) -> dict[str, Any]:
        inc = state["incident"]
        obs: dict[str, Any] = dict(state.get("observations") or {})
        services = list(dict.fromkeys([s for s in [inc.get("primary_service"), *inc.get("affected_services", [])] if s]))[:6]
        health: dict[str, Any] = {}
        logs: list[dict[str, Any]] = []
        for key in services:
            if data := self._tool(rc, "get_service_health", {"service_key": key}):
                health[key] = {"status": data["status"], "summary": data["summary"], "metrics": data["metrics"]}
            if data := self._tool(rc, "get_recent_synthetic_logs", {"service_key": key, "limit": 12}):
                logs.extend(line for line in data["lines"] if line["level"] in ("WARN", "ERROR"))
        deps: list[dict[str, Any]] = []
        if inc.get("primary_service") and (data := self._tool(rc, "get_service_dependencies",
                                                              {"service_key": inc["primary_service"]})):
            deps = data["depends_on"]
            for dep in deps[:4]:
                if dep["service"] not in health and (h := self._tool(rc, "get_service_health",
                                                                     {"service_key": dep["service"]})):
                    health[dep["service"]] = {"status": h["status"], "summary": h["summary"], "metrics": h["metrics"]}
        diagnostics: dict[str, Any] = {}
        for name, args in diagnostic_calls(inc["category"], inc.get("attributes", {})):
            if data := self._tool(rc, name, args):
                diagnostics[f"{name}:{json.dumps(args, sort_keys=True)}"] = data
        obs.update(health=health, logs=logs[-24:], dependencies=deps, diagnostics=diagnostics)
        text_parts = [h["summary"] for h in health.values()]
        text_parts += flatten_text({k: v["metrics"] for k, v in health.items()})
        text_parts += [line["message"] for line in logs]
        text_parts += flatten_text(diagnostics)
        observation_text = " \n".join(text_parts)[:20000]

        context = {"incident": inc, "observations": {"health": health, "logs": logs[-24:]}, "notes": state.get("notes")}
        context_text = "\n".join([
            f"INCIDENT (trusted record): {json.dumps({k: inc[k] for k in ('number', 'title', 'severity', 'category', 'impact')})}",
            wrap_untrusted("service_health", json.dumps({k: v["summary"] for k, v in health.items()})),
            wrap_untrusted("synthetic_logs", "\n".join(f"{x['service']} {x['level']} {x['message']}" for x in logs[-24:])),
            wrap_untrusted("analyst_notes", state.get("notes") or "(none)"),
        ])
        result: LLMResult | None = None
        try:
            result = self._llm(rc, "triage", context_text, context)
            triage = result.output.model_dump(mode="json")
            triage["search_queries"] = [neutralize(q).text[:200] for q in triage.get("search_queries", [])
                                        if q and not neutralize(q).detected][:4]
        except ProviderError:
            down = [k for k, v in health.items() if v["status"] != "healthy"]
            triage = {
                "summary": f"{inc['number']}: {inc['title']}. Non-healthy services: {', '.join(down) or 'none'}. "
                "AI triage unavailable - deterministic summary of recorded facts only.",
                "severity_assessment": inc["severity"],
                "severity_rationale": "Declared severity (AI assessment unavailable).",
                "affected_systems": sorted(set(inc.get("affected_services", [])) | set(down)),
                "key_facts": [h["summary"][:200] for h in health.values() if h["status"] != "healthy"][:8],
                "missing_information": ["AI triage unavailable; human triage required."],
                "search_queries": [inc["title"]],
            }
        return {"observations": obs, "observation_text": observation_text, "triage": triage,
                "sources": {**(state.get("sources") or {}), "triage": self._source(result)}}

    def _retrieve_evidence(self, rc: RunContext, state: WFState) -> dict[str, Any]:
        inc = state["incident"]
        triage = state.get("triage") or {}
        queries = list(dict.fromkeys([
            inc["title"],
            f"{inc['category'].replace('_', ' ')} {inc.get('primary_service') or ''} runbook remediation",
            *triage.get("search_queries", []),
        ]))[:4]
        # Re-entry after an interruption must not duplicate evidence labels.
        rc.db.execute(delete(Evidence).where(Evidence.investigation_id == rc.run.id))
        candidates: dict[str, dict[str, Any]] = {}
        sufficient = False
        excluded = 0
        reasons: list[str] = []
        top_score: float | None = None
        retrieval_failed = False
        for q in queries:
            data = self._tool(rc, "search_authorized_runbooks", {"query": q[:300], "top_k": 4})
            if data is None:
                retrieval_failed = True
                continue
            sufficient = sufficient or data["sufficient"]
            excluded = max(excluded, data["excluded_unauthorized"])
            reasons.append(data["reason"])
            if data.get("top_score") is not None:
                top_score = max(top_score or -1.0, data["top_score"])
            for item in data["results"]:
                prev = candidates.get(item["chunk_id"])
                if prev is None or item["rerank_score"] > prev["rerank_score"]:
                    candidates[item["chunk_id"]] = item
        ranked = sorted(candidates.values(), key=lambda r: -r["rerank_score"])[:6]
        evidence: list[dict[str, Any]] = []

        def add(kind: str, title: str, text: str, **extra: Any) -> None:
            label = f"E{len(evidence) + 1}"
            evidence.append({"label": label, "kind": kind, "title": title[:200], "text": text[:1500],
                             "excerpt": text[:600], **extra})

        for r in ranked:
            add("runbook", r["title"], f"{r['section']}\n{r['content']}", version=r["version"], section=r["section"],
                chunk_ref=r["chunk_ref"], citation=r["citation"], score=r["rerank_score"],
                classification=r["classification"], injection_detected=r["injection_detected"],
                document_id=r["document_id"], chunk_id=r["chunk_id"])
        if hist := self._tool(rc, "search_incident_history", {"incident_id": inc["incident_id"], "limit": 3}):
            for h in hist["incidents"]:
                add("incident_history", f"{h['number']}: {h['title']}", h["resolution_summary"],
                    source_ref=h["number"], classification=h["classification"],
                    citation=f"Incident history {h['number']} ({h['detected_at'][:10]})")
        obs = state.get("observations") or {}
        for key, h in (obs.get("health") or {}).items():
            if h["status"] != "healthy":
                add("metric", f"Service health: {key}", h["summary"], source_ref=key, citation=f"Live synthetic health: {key}")
        for line in [x for x in obs.get("logs", []) if x["level"] == "ERROR"][:4]:
            add("log", f"Log: {line['service']} {line['ts'][:19]}", line["message"], source_ref=line["service"],
                citation=f"Synthetic log {line['service']} @ {line['ts'][:19]}")
        for name, data in (obs.get("diagnostics") or {}).items():
            add("tool_result", f"Diagnostic: {name.split(':')[0]}", " ".join(flatten_text(data))[:1500],
                source_ref=name.split(":")[0], citation=f"Tool result: {name.split(':')[0]}")
        evidence = evidence[:15]
        for ev in evidence:
            rc.db.add(Evidence(
                investigation_id=rc.run.id, label=ev["label"], kind=ev["kind"], document_id=ev.get("document_id"),
                chunk_id=ev.get("chunk_id"), source_ref=ev.get("source_ref"), title=ev["title"],
                version=ev.get("version"), section=ev.get("section"), chunk_ref=ev.get("chunk_ref"),
                classification=ev.get("classification"), score=ev.get("score"), excerpt=ev["excerpt"],
                injection_detected=bool(ev.get("injection_detected")),
            ))
        runbook_count = sum(1 for e in evidence if e["kind"] == "runbook")
        if retrieval_failed and not runbook_count:
            reason = "Knowledge retrieval failed; no runbook evidence available."
        elif not sufficient:
            reason = "Retrieved runbook evidence is weak for this incident: " + (reasons[0] if reasons else "no matches")
        else:
            reason = next((r for r in reasons if r.startswith("Top")), "Sufficient runbook evidence retrieved.")
        retrieval = {"sufficient": bool(sufficient and runbook_count), "reason": reason, "queries": queries,
                     "excluded_unauthorized": excluded, "top_score": top_score, "runbook_evidence": runbook_count,
                     "retrieval_failed": retrieval_failed}
        if retrieval_failed:
            rc.degraded.append("retrieval_unavailable")
        return {"evidence": evidence, "retrieval": retrieval}

    def _diagnose(self, rc: RunContext, state: WFState) -> dict[str, Any]:
        retrieval = state.get("retrieval") or {}
        evidence = state.get("evidence") or []
        if not retrieval.get("sufficient"):
            return {"diagnosis": {"summary": "Abstained: insufficient authorized evidence.", "hypotheses": [],
                                  "abstained": True, "abstention_reason": retrieval.get("reason", "Insufficient evidence."),
                                  "conflicting_evidence": False},
                    "sources": {**(state.get("sources") or {}), "diagnosis": "deterministic"}}
        context = {"incident": state["incident"], "triage": state.get("triage"), "retrieval": retrieval,
                   "observation_text": state.get("observation_text", ""),
                   "evidence": [{"label": e["label"], "kind": e["kind"], "text": f"{e['title']}\n{e['text']}"} for e in evidence]}
        context_text = "\n".join([
            f"TRIAGE: {json.dumps(state.get('triage'))[:3000]}",
            *[wrap_untrusted(f"evidence {e['label']} ({e['kind']}: {e['title']})", e["text"]) for e in evidence],
        ])
        try:
            result = self._llm(rc, "diagnosis", context_text, context)
        except ProviderError as exc:
            return {"diagnosis": {"summary": "AI diagnosis unavailable; no findings were fabricated.", "hypotheses": [],
                                  "abstained": True, "unavailable": True,
                                  "abstention_reason": f"Model gateway error ({exc.code}). Deterministic observations "
                                  "and evidence remain available for human diagnosis.",
                                  "conflicting_evidence": False},
                    "sources": {**(state.get("sources") or {}), "diagnosis": "unavailable"}}
        diagnosis = result.output.model_dump(mode="json")
        valid = {e["label"] for e in evidence}
        removed = 0
        for h in diagnosis["hypotheses"]:
            for key in ("supporting_evidence", "contradicting_evidence"):
                kept = [lbl for lbl in h[key] if lbl in valid]
                removed += len(h[key]) - len(kept)
                h[key] = kept
            h["unsupported"] = not h["supporting_evidence"]
        diagnosis["hypotheses"].sort(key=lambda h: -h["confidence"])
        diagnosis["invalid_citations_removed"] = removed
        hyps = diagnosis["hypotheses"]
        if len(hyps) > 1 and hyps[0]["confidence"] - hyps[1]["confidence"] < 0.1:
            diagnosis["conflicting_evidence"] = True
        if hyps and hyps[0]["unsupported"] and not diagnosis["abstained"]:
            diagnosis.update(abstained=True, abstention_reason="Top hypothesis has no valid supporting evidence.")
        return {"diagnosis": diagnosis, "sources": {**(state.get("sources") or {}), "diagnosis": self._source(result)}}

    def _plan_remediation(self, rc: RunContext, state: WFState) -> dict[str, Any]:
        diag = state.get("diagnosis") or {}
        if diag.get("abstained") or diag.get("conflicting_evidence") or not diag.get("hypotheses"):
            checks = sorted({c for h in diag.get("hypotheses", []) for c in h.get("further_checks", [])})[:6]
            why = "conflicting evidence" if diag.get("conflicting_evidence") else "insufficient or unavailable evidence"
            return {"plan": {"summary": f"No remediation proposed due to {why}; only human-led read-only checks.",
                             "actions": [], "manual_steps": checks or ["Escalate to the owning team for manual diagnosis."],
                             "not_recommended": [], "evidence_refs": []},
                    "plan_version": state.get("plan_version", 1),
                    "sources": {**(state.get("sources") or {}), "plan": "deterministic"}}
        tools_catalog = [
            {"name": name, "risk": ACTION_CATALOG[name].risk.value, "description": ACTION_CATALOG[name].description,
             "allowed_targets": list(ACTION_CATALOG[name].allowed_targets),
             "args_schema": MUTATING_ARGS[name].model_json_schema()}
            for name in MUTATING_ARGS
        ]
        evidence = state.get("evidence") or []
        context = {"incident": state["incident"], "diagnosis": diag, "observations": state.get("observations", {}),
                   "allowed_tools": tools_catalog}
        context_text = "\n".join([
            f"DIAGNOSIS: {json.dumps(diag)[:4000]}",
            f"ALLOWED_TOOLS: {json.dumps(tools_catalog)[:6000]}",
            *[wrap_untrusted(f"evidence {e['label']}", e["excerpt"]) for e in evidence],
        ])
        try:
            result = self._llm(rc, "remediation_plan", context_text, context)
        except ProviderError as exc:
            return {"plan": {"summary": f"AI planning unavailable ({exc.code}); no actions proposed.", "actions": [],
                             "manual_steps": ["Plan remediation manually using the retrieved runbooks."],
                             "not_recommended": [], "evidence_refs": []},
                    "plan_version": state.get("plan_version", 1),
                    "sources": {**(state.get("sources") or {}), "plan": "unavailable"}}
        plan = result.output.model_dump(mode="json")
        valid = {e["label"] for e in evidence}
        plan["evidence_refs"] = [lbl for lbl in plan.get("evidence_refs", []) if lbl in valid]
        for a in plan["actions"]:
            a["evidence_refs"] = [lbl for lbl in a.get("evidence_refs", []) if lbl in valid]
        return {"plan": plan, "plan_version": state.get("plan_version", 1),
                "sources": {**(state.get("sources") or {}), "plan": self._source(result)}}

    def _governance_review(self, rc: RunContext, state: WFState) -> dict[str, Any]:
        plan = state.get("plan") or {}
        evidence = state.get("evidence") or []
        context = {"plan": plan, "incident": state["incident"],
                   "catalog": {k: v.risk.value for k, v in ACTION_CATALOG.items()},
                   "prohibited": sorted(PROHIBITED_ACTIONS),
                   "evidence_classifications": [e["classification"] for e in evidence if e.get("classification")]}
        context_text = f"PLAN: {json.dumps(plan)[:5000]}\nRISK_CATALOG: {json.dumps(context['catalog'])}"
        try:
            result = self._llm(rc, "governance_review", context_text, context)
            review = result.output.model_dump(mode="json")
            review["advisory_only"] = True
        except ProviderError as exc:
            result = None
            review = {"summary": f"Advisory review unavailable ({exc.code}). The deterministic policy engine still "
                      "enforces every rule.", "policy_constraints": [], "data_exposure_concerns": [],
                      "approval_recommendations": [], "prohibited_actions_detected": [], "advisory_only": True}
        return {"governance": review, "sources": {**(state.get("sources") or {}), "governance": self._source(result)}}

    def _policy_gate(self, rc: RunContext, state: WFState) -> dict[str, Any]:
        inc = rc.incident
        assert inc is not None
        plan = state.get("plan") or {}
        if not rc.dry_run:
            invalidated = self.approvals.invalidate_for_incident(rc.db, inc.id, exclude_investigation_id=rc.run.id,
                                                                 actor=rc.requester)
            if invalidated:
                self._emit(rc, "approval_invalidated", "info",
                           f"{invalidated} older pending approval(s) invalidated (plan superseded).",
                           agent=AGENTS["policy_gate"])
        outcomes = self.actions.gate_plan(rc.db, run=rc.run, incident=inc, requester=rc.requester,
                                          planned=plan.get("actions", []), dry_run=rc.dry_run)
        for o in outcomes:
            d = o["decision"]
            self._emit(rc, "policy_decision", d["decision"], f"Step {o['step']} {o['tool_name']}: {d['explanation']}",
                       agent=AGENTS["policy_gate"], tool=o["tool_name"],
                       payload={"rule_ids": d["rule_ids"], "risk_level": d["risk_level"], "action_id": o["action_id"],
                                "approval_id": o["approval_id"]})
        alternatives = []
        for alt in plan.get("not_recommended", []):
            d = self.policy.evaluate_action(rc.requester, tool_name=alt["tool_name"], target_resource=None,
                                            incident_tenant_id=inc.tenant_id, incident_status=inc.status,
                                            incident_classification=inc.classification)
            alternatives.append({"tool_name": alt["tool_name"], "reason": alt["reason"],
                                 "decision": d.decision, "explanation": d.explanation})
        risks = [RiskLevel(o["decision"]["risk_level"]) for o in outcomes]
        rc.run.risk_level = max(risks, key=RISK_ORDER.index).value if risks else None
        counts = {k: sum(1 for o in outcomes if o["decision"]["decision"] == k) for k in ("allow", "deny", "require_approval")}
        if rc.dry_run:
            phase = "reporting"
        elif counts["require_approval"]:
            phase = "awaiting_approval"
        elif counts["allow"]:
            phase = "execution"
        else:
            phase = "reporting"
        rc.db.commit()
        return {"policy": {"decisions": outcomes, "alternatives": alternatives, "counts": counts,
                           "policy_version": POLICY_VERSION},
                "phase": phase}

    def _execute_actions(self, rc: RunContext, state: WFState) -> dict[str, Any]:
        self.approvals.expire_stale(rc.db, rc.run.tenant_id)
        system = Actor(user_id="system", username="simulated-executor", role="system", tenant_id=rc.run.tenant_id)
        actions = rc.db.execute(select(ActionRecord).where(ActionRecord.investigation_id == rc.run.id)
                                .order_by(ActionRecord.step_index)).scalars().all()
        by_step = {a.step_index: a for a in actions}
        for action in actions:
            if action.status == ActionStatus.EXECUTING.value:
                action.status = ActionStatus.FAILED.value
                action.error_code = "interrupted_during_execution"
                action.result = {"message": "Execution was interrupted; state must be verified. Not retried automatically."}
                rc.db.commit()
            if action.status not in (ActionStatus.APPROVED.value, ActionStatus.APPROVED_BY_POLICY.value):
                continue
            dep = by_step.get(action.depends_on_step) if action.depends_on_step else None
            if dep is not None and dep.status != ActionStatus.SUCCEEDED.value:
                self.actions.mark_skipped(rc.db, action, system, f"dependency_step_{dep.step_index}_{dep.status}")
            else:
                self.actions.execute(rc.db, action.id, actor=system)
            rc.db.refresh(action)
            self._emit(rc, "action_executed", action.status,
                       f"[SIMULATED] Step {action.step_index} {action.tool_name} -> {action.status}"
                       + (f" ({action.error_code})" if action.error_code else ""),
                       agent=AGENTS["execute_actions"], tool=action.tool_name,
                       payload={"action_id": action.id, "error_code": action.error_code, "result": action.result})
        summary = {s: [a.id for a in actions if a.status == s] for s in
                   ("succeeded", "failed", "skipped", "rejected", "expired", "cancelled", "denied", "invalidated")}
        return {"execution": summary, "phase": "verification"}

    def _verify(self, rc: RunContext, state: WFState) -> dict[str, Any]:
        inc = rc.incident
        assert inc is not None
        system = Actor(user_id="system", username="verification-agent", role="system", tenant_id=rc.run.tenant_id)
        succeeded = rc.db.execute(select(ActionRecord).where(ActionRecord.investigation_id == rc.run.id,
                                                             ActionRecord.status == ActionStatus.SUCCEEDED.value)
                                  .order_by(ActionRecord.step_index)).scalars().all()
        for action in succeeded:
            self.actions.verify(rc.db, action, actor=system, ctx=rc.tool_ctx)
        resolution = self._tool(rc, "verify_incident_resolution", {"incident_id": inc.id})
        verification: dict[str, Any]
        if resolution is None:
            verification = {"status": "error", "checks": [], "summary": "Verification tools unavailable."}
        else:
            verification = {"status": resolution["status"], "checks": resolution["checks"],
                            "passed": resolution["passed"], "total": resolution["total"]}
            rc.db.refresh(inc)
            if resolution["status"] == "partially_resolved" and inc.status not in (IncidentStatus.RESOLVED.value,):
                mark_incident(rc.db, inc, IncidentStatus.MITIGATED, "Partially resolved after simulated remediation.")
            rc.db.commit()
        checks = [{"name": c["name"], "passed": c["passed"]} for c in verification.get("checks", [])]
        try:
            result = self._llm(rc, "verification_summary", f"CHECKS: {json.dumps(verification)}",
                               {"checks": checks, "status": verification["status"]})
            verification.update(result.output.model_dump(mode="json"))
        except ProviderError:
            verification["summary"] = (f"Deterministic verification: {verification['status']} "
                                       f"({verification.get('passed', 0)}/{verification.get('total', 0)} checks).")
        return {"verification": verification}

    def _compose_report(self, rc: RunContext, state: WFState) -> dict[str, Any]:
        diag = state.get("diagnosis") or {}
        evidence = {e["label"]: e for e in state.get("evidence") or []}
        actions = [] if rc.dry_run else [
            {"step_index": a.step_index, "tool_name": a.tool_name, "status": a.status,
             "verification_status": a.verification_status}
            for a in rc.db.execute(select(ActionRecord).where(ActionRecord.investigation_id == rc.run.id)
                                   .order_by(ActionRecord.step_index)).scalars()
        ]
        verification = state.get("verification")
        if state.get("abort_reason"):
            outcome = InvestigationOutcome.ABORTED
        elif rc.dry_run:
            outcome = InvestigationOutcome.DRY_RUN
        elif verification and any(a["status"] == ActionStatus.SUCCEEDED.value or a["status"] == ActionStatus.ROLLED_BACK.value
                                  for a in actions):
            outcome = InvestigationOutcome(verification["status"]) if verification["status"] in (
                "resolved", "partially_resolved", "unresolved") else InvestigationOutcome.UNRESOLVED
        elif diag.get("abstained"):
            outcome = InvestigationOutcome.INSUFFICIENT_EVIDENCE
        else:
            outcome = InvestigationOutcome.NO_ACTION_TAKEN
        cited: list[str] = []
        top = (diag.get("hypotheses") or [None])[0] if not diag.get("abstained") else None
        if top:
            cited += top.get("supporting_evidence", [])
        cited += (state.get("plan") or {}).get("evidence_refs", [])
        citations = [f"[{lbl}] {evidence[lbl].get('citation') or evidence[lbl]['title']}"
                     for lbl in dict.fromkeys(cited) if lbl in evidence]
        context = {"incident": state.get("incident", {}), "triage": state.get("triage"), "diagnosis": diag,
                   "plan": state.get("plan"), "actions": actions, "verification": verification,
                   "outcome": outcome.value, "citations": citations}
        result: LLMResult | None = None
        try:
            if state.get("abort_reason") == "token_budget_exceeded":
                raise ProviderError("token_budget_exceeded")
            result = self._llm(rc, "final_report", f"STATE: {json.dumps(context, default=str)[:8000]}", context)
            report = result.output.model_dump(mode="json")
        except (ProviderError, WorkflowAbort):
            inc = state.get("incident") or {}
            report = {
                "title": f"Incident report - {inc.get('number', '')}: {inc.get('title', '')}"[:200],
                "executive_summary": f"Outcome: {outcome.value}. AI report composer unavailable; this deterministic "
                "report lists recorded facts only.",
                "findings": list((state.get("triage") or {}).get("key_facts", []))[:6],
                "root_cause": top["description"] if top else None,
                "actions_taken": [f"Step {a['step_index']}: {a['tool_name']} -> {a['status']}" for a in actions],
                "evidence_citations": citations,
                "limitations": ["Deterministic fallback report (model gateway unavailable)."],
                "next_steps": (state.get("plan") or {}).get("manual_steps", [])[:6],
            }
        report["evidence_citations"] = citations  # citations are always computed deterministically
        if state.get("abort_reason"):
            report.setdefault("limitations", []).insert(0, f"Workflow stopped safely: {state['abort_reason']}.")
        if rc.degraded:
            report.setdefault("limitations", []).append("Degraded mode: " + "; ".join(sorted(set(rc.degraded)))[:500])
        source = self._source(result)
        report["generated_by"] = {"mock": "MOCK MODE (deterministic mock provider - not model inference)",
                                  "live_model": f"LIVE MODEL {self.gateway.provider.model}",
                                  "deterministic": "DETERMINISTIC FALLBACK (no model output)"}[source]
        return {"report": report, "outcome": outcome.value, "phase": "done",
                "sources": {**(state.get("sources") or {}), "report": source}}

    # ==================================================================== graph
    def _wrap(self, rc: RunContext, name: str, fn: Any) -> Any:
        agent = AGENTS[name]

        def node(state: WFState) -> dict[str, Any]:
            if name in (state.get("completed") or []):
                return {}
            rc.db.refresh(rc.run)
            if rc.run.status == InvestigationStatus.CANCELLED.value:
                raise WorkflowAbort("cancelled")
            steps = int(state.get("step_count", 0)) + 1
            update: dict[str, Any]
            # The final report step is always allowed so every run ends with an explanation.
            if steps > self.settings.workflow_max_steps and name != "compose_report":
                update = {"abort_reason": "max_steps_exceeded"}
            elif time.monotonic() > rc.deadline and name != "compose_report":
                update = {"abort_reason": "workflow_timeout"}
            else:
                token = agent_var.set(agent)
                rc.tool_ctx.agent = agent
                self._emit(rc, "step_started", "running", f"{agent} started", agent=agent)
                started = time.perf_counter()
                status = "completed"
                try:
                    update = fn(rc, state)
                except ToolBudgetExceeded:
                    update, status = {"abort_reason": "max_tool_calls_exceeded"}, "failed"
                except WorkflowAbort as exc:
                    if exc.code == "cancelled":
                        raise
                    update, status = {"abort_reason": exc.code}, "failed"
                except Exception as exc:  # noqa: BLE001 - convert to a safe, sanitized abort
                    rc.db.rollback()
                    log.error("workflow node failed", extra={"node": name, "error_code": type(exc).__name__,
                                                             "trace_tail": traceback.format_exc(limit=2)[-600:]})
                    update, status = {"abort_reason": f"internal_error:{name}:{type(exc).__name__}"}, "failed"
                finally:
                    agent_var.reset(token)
                duration = int((time.perf_counter() - started) * 1000)
                if status == "completed" and duration > self.settings.workflow_step_timeout_seconds * 1000:
                    update["abort_reason"] = f"step_timeout:{name}"
                    status = "failed"
                self._emit(rc, "step_completed" if status == "completed" else "step_failed", status,
                           f"{agent} {status}" + (f": {update.get('abort_reason')}" if status == "failed" else ""),
                           agent=agent, duration_ms=duration, payload={"node": name})
            update["step_count"] = steps
            update["completed"] = [*(state.get("completed") or []), name]
            update["degraded_reasons"] = sorted(set(rc.degraded))
            self._persist(rc, {**state, **update}, name)
            return update

        return node

    def build(self, rc: RunContext) -> Any:
        g: StateGraph[WFState] = StateGraph(WFState)
        nodes = {
            "validate_incident": self._validate_incident, "triage": self._triage,
            "retrieve_evidence": self._retrieve_evidence, "diagnose": self._diagnose,
            "plan_remediation": self._plan_remediation, "governance_review": self._governance_review,
            "policy_gate": self._policy_gate, "execute_actions": self._execute_actions, "verify": self._verify,
            "compose_report": self._compose_report,
        }
        for name, fn in nodes.items():
            g.add_node(name, self._wrap(rc, name, fn))

        def entry(state: WFState) -> str:
            phase = state.get("phase", "analysis")
            return {"execution": "execute_actions", "verification": "execute_actions",
                    "reporting": "compose_report"}.get(phase, "validate_incident")

        def forward(nxt: str) -> Any:
            return lambda s: "compose_report" if s.get("abort_reason") else nxt

        def after_gate(state: WFState) -> str:
            if state.get("abort_reason"):
                return "compose_report"
            return {"awaiting_approval": END, "execution": "execute_actions"}.get(state.get("phase", ""), "compose_report")

        g.add_conditional_edges(START, entry, {"validate_incident": "validate_incident",
                                               "execute_actions": "execute_actions", "compose_report": "compose_report"})
        chain = ANALYSIS_NODES[:-1]
        for cur, nxt in zip(chain, ANALYSIS_NODES[1:], strict=True):
            g.add_conditional_edges(cur, forward(nxt), {nxt: nxt, "compose_report": "compose_report"})
        g.add_conditional_edges("policy_gate", after_gate,
                                {END: END, "execute_actions": "execute_actions", "compose_report": "compose_report"})
        g.add_conditional_edges("execute_actions", forward("verify"), {"verify": "verify", "compose_report": "compose_report"})
        g.add_edge("verify", "compose_report")
        g.add_edge("compose_report", END)
        return g.compile()

    # ===================================================================== run
    def run(self, db: Session, run: InvestigationRun, requester: Actor) -> InvestigationRun:
        """Execute (or resume) a run that the caller has already moved to `running`."""
        investigation_id_var.set(run.id)
        incident = db.get(Incident, run.incident_id)
        rc = RunContext(
            db=db, run=run, incident=incident, requester=requester,
            deadline=time.monotonic() + self.settings.workflow_total_timeout_seconds,
            tool_ctx=ToolContext(db=db, actor=requester, settings=self.settings, retriever=self.retriever,
                                 investigation_id=run.id),
            tool_calls=run.tool_call_count or 0,
            tokens=(run.input_tokens or 0) + (run.output_tokens or 0),
        )
        rc.tool_ctx.budget = lambda: self._budget(rc)
        state: dict[str, Any] = dict(run.state or {})
        state.setdefault("investigation_id", run.id)
        state.setdefault("phase", "analysis")
        state.setdefault("completed", [])
        state.setdefault("step_count", 0)
        state.setdefault("notes", run.notes)
        rc.degraded = list(state.get("degraded_reasons") or [])
        if state["phase"] in ("execution", "verification"):
            state["completed"] = [n for n in state["completed"] if n in ANALYSIS_NODES]
        self._emit(rc, "status_change", "running", f"Workflow {WORKFLOW_VERSION} running (phase: {state['phase']}).",
                   agent="Orchestrator")
        final: dict[str, Any] = state
        try:
            final = self.build(rc).invoke(state, config={"recursion_limit": self.settings.workflow_max_steps + 6})
            db.refresh(run)
            phase = final.get("phase")
            if phase == "awaiting_approval":
                run.status = InvestigationStatus.AWAITING_APPROVAL.value
                if incident is not None and not rc.dry_run:
                    mark_incident(db, incident, IncidentStatus.AWAITING_APPROVAL,
                                  "Simulated remediation awaiting human approval.", source="bankops-ai")
            else:
                run.status = (InvestigationStatus.FAILED if final.get("abort_reason") else InvestigationStatus.COMPLETED).value
                run.outcome = final.get("outcome")
                run.error_code = final.get("abort_reason")
                run.completed_at = utcnow()
                if incident is not None and not rc.dry_run and incident.status == IncidentStatus.AWAITING_APPROVAL.value:
                    mark_incident(db, incident, IncidentStatus.INVESTIGATING, "Approval phase finished.", source="bankops-ai")
        except WorkflowAbort as exc:  # cancellation
            db.rollback()
            db.refresh(run)
            run.status = InvestigationStatus.CANCELLED.value
            run.error_code = exc.code
            run.completed_at = utcnow()
        except GraphRecursionError:
            db.rollback()
            db.refresh(run)
            run.status = InvestigationStatus.FAILED.value
            run.error_code = "recursion_limit"
            run.outcome = InvestigationOutcome.ABORTED.value
            run.completed_at = utcnow()
        run.lock_token = None
        run.degraded = bool(rc.degraded)
        run.model_mode = "DEGRADED" if rc.degraded and run.model_mode != "MOCK" else run.model_mode
        record_audit(db, tenant_id=run.tenant_id, action=f"investigation.{run.status}", resource_type="investigation",
                     resource_id=run.id, actor=requester, investigation_id=run.id,
                     outcome="failure" if run.status == InvestigationStatus.FAILED.value else "success",
                     details={"outcome": run.outcome, "error_code": run.error_code, "steps": run.step_count,
                              "tool_calls": run.tool_call_count, "degraded": rc.degraded[:10]})
        self._emit(rc, "status_change", run.status,
                   f"Investigation {run.status}" + (f" (outcome: {run.outcome})" if run.outcome else ""),
                   agent="Orchestrator", payload={"outcome": run.outcome, "error_code": run.error_code})
        db.commit()
        return run
