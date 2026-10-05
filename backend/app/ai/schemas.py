"""Typed, bounded output contracts for every agent. Model output is untrusted until validated."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class TriageOutput(_Strict):
    summary: str = Field(max_length=1500)
    severity_assessment: Literal["critical", "high", "medium", "low"]
    severity_rationale: str = Field(max_length=600)
    affected_systems: list[str] = Field(default_factory=list, max_length=12)
    key_facts: list[str] = Field(default_factory=list, max_length=10)
    missing_information: list[str] = Field(default_factory=list, max_length=8)
    search_queries: list[str] = Field(default_factory=list, max_length=4)


class Hypothesis(_Strict):
    id: str = Field(pattern=r"^H\d{1,2}$")
    title: str = Field(max_length=200)
    description: str = Field(max_length=800)
    root_cause_category: str = Field(max_length=64)
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_rationale: str = Field(max_length=600)
    supporting_evidence: list[str] = Field(default_factory=list, max_length=10)
    contradicting_evidence: list[str] = Field(default_factory=list, max_length=10)
    further_checks: list[str] = Field(default_factory=list, max_length=6)


class DiagnosisOutput(_Strict):
    summary: str = Field(max_length=1200)
    hypotheses: list[Hypothesis] = Field(default_factory=list, max_length=5)
    abstained: bool = False
    abstention_reason: str | None = Field(default=None, max_length=600)
    conflicting_evidence: bool = False


class PlannedAction(_Strict):
    step: int = Field(ge=1, le=6)
    tool_name: str = Field(max_length=80)
    target_resource: str = Field(max_length=100)
    parameters: dict[str, Any] = Field(default_factory=dict)
    rationale: str = Field(max_length=800)
    expected_effect: str = Field(max_length=500)
    risks: str = Field(max_length=500)
    prerequisites: list[str] = Field(default_factory=list, max_length=6)
    rollback_option: str = Field(default="", max_length=400)
    depends_on_step: int | None = Field(default=None, ge=1, le=6)
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)


class RejectedAlternative(_Strict):
    tool_name: str = Field(max_length=80)
    reason: str = Field(max_length=400)


class RemediationPlan(_Strict):
    summary: str = Field(max_length=1200)
    actions: list[PlannedAction] = Field(default_factory=list, max_length=6)
    manual_steps: list[str] = Field(default_factory=list, max_length=8)
    not_recommended: list[RejectedAlternative] = Field(default_factory=list, max_length=6)
    evidence_refs: list[str] = Field(default_factory=list, max_length=10)


class ApprovalRecommendation(_Strict):
    step: int = Field(ge=1, le=6)
    recommendation: str = Field(max_length=400)


class GovernanceReview(_Strict):
    summary: str = Field(max_length=1200)
    policy_constraints: list[str] = Field(default_factory=list, max_length=10)
    data_exposure_concerns: list[str] = Field(default_factory=list, max_length=8)
    approval_recommendations: list[ApprovalRecommendation] = Field(default_factory=list, max_length=6)
    prohibited_actions_detected: list[str] = Field(default_factory=list, max_length=10)
    advisory_only: bool = True


class VerificationSummary(_Strict):
    summary: str = Field(max_length=800)
    residual_risks: list[str] = Field(default_factory=list, max_length=6)


class FinalReport(_Strict):
    title: str = Field(max_length=200)
    executive_summary: str = Field(max_length=1500)
    findings: list[str] = Field(default_factory=list, max_length=10)
    root_cause: str | None = Field(default=None, max_length=600)
    actions_taken: list[str] = Field(default_factory=list, max_length=10)
    evidence_citations: list[str] = Field(default_factory=list, max_length=12)
    limitations: list[str] = Field(default_factory=list, max_length=10)
    next_steps: list[str] = Field(default_factory=list, max_length=8)


class JudgeScore(_Strict):
    faithfulness: int = Field(ge=1, le=5)
    completeness: int = Field(ge=1, le=5)
    safety: int = Field(ge=1, le=5)
    rationale: str = Field(max_length=800)
