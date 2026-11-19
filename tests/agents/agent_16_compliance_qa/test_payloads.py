# ruff: noqa: PT018
"""Agent 16 payload registration.

The three input schemas are registered; the outputs (``compliance_gate``, ``quality_score``,
``publication_authorisation``) are plain mappings with no model, so they are not registered (the
registry refuses them: the executor fails closed on an Agent 16 output until a model exists).
"""

import json

import pytest

from agent_16_compliance_qa.assembler import ComplianceGateInput
from agent_16_compliance_qa.authorisation.stage import (
    AuthorisationInput,
    PublicationAuthorisationStage,
    PublicationAuthorisationWorker,
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


def test_compliance_gate_input_round_trips_and_the_output_is_not_registered() -> None:
    w = gate_world()
    assert isinstance(round_trip(w.ti.payload), ComplianceGateInput)
    out = w.stage.run(w.ti, ctx_of(w.ti))
    assert out.status is OutputStatus.SUCCEEDED and out.payload is not None
    assert out.payload.payload_schema == "agent_16.compliance_gate.output"
    with pytest.raises(SchemaInvalidError):  # fail closed: no model, no registration
        loaded_registry().validate(
            out.payload.payload_schema, out.payload.payload_schema_version, out.payload.data or {}
        )


def test_quality_score_input_round_trips() -> None:
    from agent_16_compliance_qa.scoring.stage import QualityScoreInput

    w = score_world()
    # the model adds the defaulted optional ``audience_level``
    assert isinstance(round_trip(w.ti.payload, exact=False), QualityScoreInput)
    out = w.stage.run(w.ti, ctx_of(w.ti))
    assert out.status is OutputStatus.SUCCEEDED and out.payload is not None
    assert out.payload.payload_schema == "agent_16.quality_score.output"


def test_publication_authorisation_input_round_trips() -> None:
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
