# ruff: noqa: PT018
"""Agent 16 payload registration.

The three input schemas and the three output schemas (blueprint 8.2, 8.4, 8.5) are registered;
each real emitted output validates through the loaded registry and round-trips unchanged. The
``svc_s02`` pair is registered from the ``svc_s02`` sub-package (CCR-282).
"""

import json

import pytest

from agent_16_compliance_qa.assembler import ComplianceGateInput
from agent_16_compliance_qa.authorisation.stage import (
    AuthorisationInput,
    PublicationAuthorisationStage,
    PublicationAuthorisationWorker,
)
from agent_16_compliance_qa.payload_models import (
    ComplianceGateOutput,
    PublicationAuthorisationOutput,
    QualityScoreOutput,
)
from amw_core.enums import OutputStatus
from amw_core.errors import SchemaInvalidError
from tests.agents.agent_16_compliance_qa.support import FixedClock, config
from tests.agents.agent_16_compliance_qa.test_auth_stage import AUDIT, Writer, world
from tests.agents.agent_16_compliance_qa.test_entry_points import score_world
from tests.agents.agent_16_compliance_qa.test_stages import (
    NOW,
    Storage,
    Tenancy,
    ctx_of,
    gate_world,
    task_input,
)
from tests.agents.payload_support import loaded_registry, round_trip

pytestmark = pytest.mark.contract


def test_compliance_gate_input_and_output_round_trip() -> None:
    w = gate_world()
    assert isinstance(round_trip(w.ti.payload), ComplianceGateInput)
    out = w.stage.run(w.ti, ctx_of(w.ti))
    assert out.status is OutputStatus.SUCCEEDED and out.payload is not None
    assert out.payload.payload_schema == "agent_16.compliance_gate.output"
    assert isinstance(round_trip(out.payload), ComplianceGateOutput)
    broken = {k: v for k, v in (out.payload.data or {}).items() if k != "verdict"}
    with pytest.raises(SchemaInvalidError):  # a payload that misses a required field is refused
        loaded_registry().validate(
            out.payload.payload_schema, out.payload.payload_schema_version, broken
        )


def test_quality_score_input_and_output_round_trip() -> None:
    from agent_16_compliance_qa.scoring.stage import QualityScoreInput

    w = score_world()
    # the model adds the defaulted optional ``audience_level``
    assert isinstance(round_trip(w.ti.payload, exact=False), QualityScoreInput)
    out = w.stage.run(w.ti, ctx_of(w.ti))
    assert out.status is OutputStatus.SUCCEEDED and out.payload is not None
    assert out.payload.payload_schema == "agent_16.quality_score.output"
    assert isinstance(round_trip(out.payload), QualityScoreOutput)


def test_publication_authorisation_input_and_output_round_trip() -> None:
    h, repo, req = world()
    stage = PublicationAuthorisationStage(config(), repo, h.a16, Writer(), AUDIT)
    worker = PublicationAuthorisationWorker(stage, Tenancy(), Storage(), FixedClock(NOW))
    ti = task_input(
        str(h.org),
        "agent_16",
        "agent_16.publication_authorisation.input",
        json.loads(req.model_dump_json()),
    )
    assert isinstance(round_trip(ti.payload), AuthorisationInput)
    out = worker.run(ti, ctx_of(ti))
    assert out.status is OutputStatus.SUCCEEDED and out.payload is not None
    assert out.payload.payload_schema == "agent_16.publication_authorisation.output"
    assert isinstance(round_trip(out.payload), PublicationAuthorisationOutput)


@pytest.mark.parametrize("identical", [False, True])
def test_uniqueness_input_and_output_round_trip(identical: bool) -> None:
    from agent_16_compliance_qa.payload_models import UniquenessCheckOutput
    from agent_16_compliance_qa.stages import UniquenessInput
    from tests.agents.agent_16_compliance_qa.test_stages import uniq_world

    stage, ti, _, _ = uniq_world(identical)
    assert isinstance(round_trip(ti.payload, exact=False), UniquenessInput)
    out = stage.run(ti, ctx_of(ti))
    assert out.status is OutputStatus.SUCCEEDED and out.payload is not None
    assert out.payload.payload_schema == "svc_s02.uniqueness_check.output"
    assert isinstance(round_trip(out.payload), UniquenessCheckOutput)
