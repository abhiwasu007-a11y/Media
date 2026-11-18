"""ConceptStep (F-10): prompt rendering and parsing. The model sees IDs and labels, never pixels."""

import json
from dataclasses import dataclass

from pydantic import ValidationError

from agent_11_thumbnail_design.models import StepIn, StepOut
from amw_adapters.llm.protocol import LlmMessage, LlmRequest
from amw_core.errors import InvalidJsonError, OutputSchemaInvalidError

INPUT_OPEN = "<<<INPUT"
INPUT_CLOSE = "INPUT>>>"
PLATFORM_PACK_TOKENS = ("rp.youtube_general", "rp.finance_sebi_in")
TENANT_PACK_TOKEN = "rp.tenant_brand_safety"  # noqa: S105 - rule pack name, not a credential


@dataclass(frozen=True, slots=True)
class PromptBundle:
    """The released prompt file (immutable); hash recorded with every call."""

    prompt_id: str
    text: str
    sha256: str


def render_request(
    step: StepIn,
    prompt: PromptBundle,
    *,
    model: str,
    max_output_tokens: int,
    temperature: float,
    timeout_ms: int,
    cache_system_prompt: bool,
    platform_packs: dict[str, str],
    tenant_pack_text: str | None,
    parse_error: str | None = None,
) -> LlmRequest:
    """Stable prefix = prompt file + PLATFORM-scope rule-pack text; the TENANT-scope pack and all
    tenant data come after the cache breakpoint, in the user message (27 4.2, CCR-025)."""
    system = prompt.text
    for token in PLATFORM_PACK_TOKENS:
        system = system.replace("{{rule_pack:" + token + "}}", platform_packs.get(token, ""))
    system = system.replace("{{rule_pack:" + TENANT_PACK_TOKEN + "}}", "")
    data = json.dumps(step.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    user = f"{INPUT_OPEN}\n{data}\n{INPUT_CLOSE}"
    if tenant_pack_text:
        user += "\n" + tenant_pack_text
    if parse_error:
        user += "\nThe previous answer failed validation: " + parse_error[:400]
    return LlmRequest(
        model=model,
        system=system,
        messages=(LlmMessage(role="user", content=user),),
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        timeout_ms=timeout_ms,
        cache_system_prompt=cache_system_prompt,
        language=step.language,
    )


def parse_output(text: str) -> StepOut:
    """Typed errors: not JSON -> AGENT.INVALID_JSON; wrong shape -> AGENT.OUTPUT_SCHEMA_INVALID."""
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidJsonError("model output is not JSON") from exc
    try:
        return StepOut.model_validate(doc)
    except ValidationError as exc:
        paths = [".".join(str(p) for p in e["loc"]) for e in exc.errors()[:5]]
        raise OutputSchemaInvalidError(
            "model output does not match the schema", details={"paths": paths}
        ) from exc
