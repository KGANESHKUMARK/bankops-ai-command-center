"""Prompt-injection detection and neutralization for untrusted content.

All retrieved documents, logs, tool results and user free text are treated as
untrusted *data*. This module removes instruction-like lines before content is
shown to a model and flags them for review. It is a heuristic defense layer;
the real safety boundary is that tools, approvals and execution are controlled by
application code and the deterministic policy engine, never by model output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "INJ-001",
        "Instruction override",
        re.compile(
            r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|any|system|"
            r"safety)\b[^.\n]{0,30}\b(instructions?|rules?|prompts?|guidelines?|polic(?:y|ies))\b",
            re.I,
        ),
    ),
    (
        "INJ-002",
        "Role/persona hijack",
        re.compile(
            r"\byou are now\b|\bact as (?:an? |the )?(?:admin|administrator|system|developer|root|approver)\b|"
            r"\bpretend (?:to be|you are)\b|\bnew persona\b",
            re.I,
        ),
    ),
    (
        "INJ-003",
        "Prompt/secret exfiltration",
        re.compile(
            r"\b(reveal|print|show|output|repeat|leak|disclose)\b[^.\n]{0,30}\b(system prompt|hidden instructions|"
            r"developer (?:message|prompt)|your instructions|api[_ ]?keys?|secrets?|credentials?|tokens?)\b",
            re.I,
        ),
    ),
    (
        "INJ-004",
        "Approval/policy bypass",
        re.compile(
            r"\b(auto[- ]?approve\w*|approve (?:all|every|each) (?:pending )?(?:actions?|requests?)|"
            r"(?:execute|run|perform) (?:it|this|them|all|every(?:thing)?|actions?|the actions?) without "
            r"(?:human )?(?:approval|review)|skip (?:the )?approvals?|bypass (?:the )?(?:approvals?|policy|"
            r"policy engine|guardrails?|controls?))\b",
            re.I,
        ),
    ),
    (
        "INJ-005",
        "Safety control tampering",
        re.compile(
            r"\b(disable|turn off|deactivate|suppress|delete)\b[^.\n]{0,20}\b(audit(?: log(?:ging)?)?|logging|"
            r"guardrails?|safety checks?|monitoring|policy engine)\b",
            re.I,
        ),
    ),
    (
        "INJ-006",
        "Chat-template / role-marker smuggling",
        re.compile(
            r"(<\|?(?:im_start|im_end|system|assistant|endoftext)\|?>|\[/?(?:INST|SYS)\]|^\s*#{0,6}\s*(?:system|"
            r"assistant|developer)\s*(?:prompt|message)?\s*:\s*(?:you|ignore|from now|new instructions)|"
            r"\bBEGIN (?:SYSTEM|ADMIN) (?:PROMPT|OVERRIDE)\b)",
            re.I | re.M,
        ),
    ),
    (
        "INJ-007",
        "Prohibited tool invocation",
        re.compile(
            r"\b(call|invoke|run|execute|trigger|use)\b[^.\n]{0,25}\b(execute_payment|transfer_funds|"
            r"modify_account_balance|delete_customer_record|execute_sql|run_shell_command|fetch_url|"
            r"drop_database_table|disable_audit_logging|purge_kafka_topic|bulk_export_customer_data|"
            r"modify_production_schema|delete_queue_messages|execute_python)\b",
            re.I,
        ),
    ),
    (
        "INJ-008",
        "Data exfiltration request",
        re.compile(
            r"\b(send|post|upload|exfiltrate|forward|email)\b[^.\n]{0,40}(https?://|\bto (?:an? )?external\b|"
            r"\bwebhook\b)",
            re.I,
        ),
    ),
    (
        "INJ-009",
        "Command/SQL payload",
        re.compile(r"(\brm\s+-rf\b|\bdrop\s+table\b|\bbash\s+-c\b|powershell\s+-e(?:nc)?\b|;\s*--\s*$)", re.I),
    ),
]

_NEGATION = re.compile(r"\b(not|never|no|don't|do not|must not|cannot|can't|prohibited|forbidden)\b", re.I)
_NEGATABLE = {"INJ-004", "INJ-005", "INJ-007"}
NEUTRALIZED_MARKER = "[NEUTRALIZED: untrusted instruction-like content removed ({ids})]"
_MARKER_IDS = re.compile(r"^\[NEUTRALIZED: [^(]*\(([A-Z0-9\-, ]+)\)\]")


@dataclass
class SanitizedText:
    text: str
    detected: bool = False
    pattern_ids: list[str] = field(default_factory=list)
    removed_lines: int = 0


def _line_patterns(line: str) -> list[str]:
    hits: list[str] = []
    for pid, _label, rx in PATTERNS:
        for match in rx.finditer(line):
            if pid in _NEGATABLE and _NEGATION.search(line[max(0, match.start() - 40) : match.start()]):
                continue
            hits.append(pid)
            break
    return hits


def detect(text: str) -> list[str]:
    ids: set[str] = set()
    for line in text.split("\n"):
        ids.update(_line_patterns(line))
    return sorted(ids)


def neutralize(text: str) -> SanitizedText:
    """Replace instruction-like lines with a visible marker; never silently drop content."""
    out: list[str] = []
    all_ids: set[str] = set()
    removed = 0
    for line in text.split("\n"):
        if line.startswith("[NEUTRALIZED:"):
            # Already neutralized (e.g. re-index of stored text): keep the marker and preserve its flags.
            out.append(line)
            removed += 1
            if match := _MARKER_IDS.search(line):
                all_ids.update(i.strip() for i in match.group(1).split(","))
            continue
        ids = _line_patterns(line)
        if ids:
            removed += 1
            all_ids.update(ids)
            out.append(NEUTRALIZED_MARKER.format(ids=", ".join(ids)))
        else:
            out.append(line)
    return SanitizedText(text="\n".join(out), detected=bool(all_ids), pattern_ids=sorted(all_ids), removed_lines=removed)


def wrap_untrusted(label: str, text: str) -> str:
    """Delimit untrusted data for prompts. Delimiter look-alikes inside content are defanged."""
    safe = text.replace("<untrusted", "&lt;untrusted").replace("</untrusted", "&lt;/untrusted")
    return f'<untrusted_data source="{label}">\n{safe}\n</untrusted_data>'


PATTERN_CATALOG = [{"id": pid, "label": label} for pid, label, _ in PATTERNS]
