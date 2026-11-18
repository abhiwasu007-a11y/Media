"""Valid example documents for every contract (fresh dicts per call so tests can mutate them)."""

from typing import Any

ORG = "org_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e9f"
OTHER_ORG = "org_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e90"
JOB = "job_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e91"
TASK = "tsk_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e92"
PROJECT = "prj_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e93"
COR = "cor_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e94"
MSG = "msg_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e95"
CST = "cst_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e96"
IDK = "idk_" + "ab" * 32
SHA = "cd" * 32
TS = "2026-01-01T00:00:00.000Z"


def blob(org: str = ORG, path: str = "jobs/x/input.json") -> str:
    return f"amw-blob://{org}/{path}"


def task_input() -> dict[str, Any]:
    return {
        "org_id": ORG,
        "job_id": JOB,
        "task_id": TASK,
        "project_id": PROJECT,
        "channel_id": None,
        "agent_id": "agent_05",
        "source_agent": "agent_01",
        "priority": "NORMAL",
        "deadline": None,
        "context_refs": [
            {
                "uri": blob(),
                "purpose": "PRIOR_OUTPUT",
                "sha256": SHA,
                "schema": "agent_04.x.output",
            },
            {"uri": "amw-blob://platform/templates/a.json", "purpose": "TEMPLATE"},
        ],
        "resource_budget": {"max_cost_micros": 500000, "currency": "INR", "max_wall_ms": 60000},
        "payload": {
            "payload_schema": "agent_05.script_draft.input",
            "payload_schema_version": "1.0.0",
            "data": {"topic": "t"},
        },
        "correlation_id": COR,
        "idempotency_key": IDK,
        "retry_count": 0,
        "schema_version": "1.0.0",
    }


def envelope(schema: str = "amw.task_input") -> dict[str, Any]:
    return {
        "org_id": ORG,
        "message_id": MSG,
        "sender": "agent_01",
        "receiver": "agent_05",
        "job_id": JOB,
        "task_id": TASK,
        "payload_ref": {
            "uri": blob(),
            "schema": schema,
            "schema_version": "1.0.0",
            "sha256": SHA,
            "size_bytes": 512,
            "media_type": "application/json",
        },
        "priority": "HIGH",
        "timestamp": TS,
        "correlation_id": COR,
        "schema_version": "1.0.0",
    }


def control() -> dict[str, Any]:
    return {
        "command": "DRAIN",
        "reason": "night window drain",
        "act_by": TS,
        "schema_version": "1.0.0",
    }


def error(code: str = "TEMPORARY.TIMEOUT", attempt_no: int = 1) -> dict[str, Any]:
    return {
        "code": code,
        "error_class": code.split(".")[0],
        "message": "call timed out",
        "retryable": True,
        "retry_after_ms": None,
        "details": {},
        "actor": "agent_05",
        "provider": "anthropic",
        "upstream_status": None,
        "upstream_code": None,
        "attempt_no": attempt_no,
        "occurred_at": TS,
        "correlation_id": COR,
    }


def resource_usage() -> dict[str, Any]:
    return {
        "cpu_ms": 10,
        "peak_rss_bytes": 1024,
        "tokens_in": 100,
        "tokens_out": 50,
        "tokens_cached_in": 0,
        "llm_calls": 1,
        "provider_calls": 1,
        "cost_estimate_micros": 1200,
        "currency": "USD",
        "cost_entry_ids": [CST],
    }


def task_output(status: str = "SUCCEEDED") -> dict[str, Any]:
    doc: dict[str, Any] = {
        "status": status,
        "payload": {
            "payload_schema": "agent_05.script_draft.output",
            "payload_schema_version": "1.0.0",
            "data_ref": blob(path="jobs/x/out.json"),
            "data_sha256": SHA,
        },
        "output_refs": [
            {
                "uri": blob(path="jobs/x/script.md"),
                "kind": "SCRIPT",
                "sha256": SHA,
                "size_bytes": 2048,
                "media_type": "text/markdown",
            }
        ],
        "quality_score": 82.5,
        "confidence": 0.7,
        "validation_results": [
            {
                "check_id": "script.length",
                "kind": "DETERMINISTIC",
                "verdict": "PASS",
                "blocking": True,
                "rule_id": "FIN-R6",
                "measured": 12,
                "threshold": "10",
                "unit": "min",
                "message": "ok",
                "evidence_ref": None,
            }
        ],
        "duration": 1500,
        "resource_usage": resource_usage(),
        "error": None,
        "next_action": {
            "type": "CONTINUE",
            "wait_reason": None,
            "escalation_level": None,
            "reason": "",
        },
        "downstream_agent": "agent_06",
        "timestamp": TS,
    }
    if status in ("FAILED", "REJECTED"):
        doc["payload"] = None
        doc["error"] = error(
            "PERMANENT.SCHEMA_INVALID", attempt_no=0 if status == "REJECTED" else 1
        )
        doc["next_action"]["type"] = "STOP"
        if status == "REJECTED":
            doc["output_refs"] = []
    if status == "SUSPENDED":
        doc["payload"] = None
        doc["next_action"] = {
            "type": "WAIT",
            "wait_reason": "AWAITING_APPROVAL",
            "escalation_level": None,
            "reason": "approval gate",
        }
    return doc
