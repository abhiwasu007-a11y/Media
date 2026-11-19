# ruff: noqa: PT018
"""Agent 13 (``amw_delivery``) payload registration: the registered models accept what the stage
really emits."""

from pathlib import Path

import pytest

from amw_core.enums import OutputStatus
from amw_delivery.models import BundleInputs, BundleManifest
from tests.agents.payload_support import round_trip
from tests.delivery.support import World
from tests.delivery.test_stage import _ctx, _data, _stage, _task

pytestmark = pytest.mark.integration


def test_file_delivery_input_and_output_round_trip(tmp_path: Path) -> None:
    w = World(tmp_path, shorts=True)
    ti = _task(w, _data(w))
    assert isinstance(round_trip(ti.payload), BundleInputs)
    out = _stage(w, tmp_path).run(ti, _ctx(ti))
    assert out.status is OutputStatus.SUCCEEDED and out.payload is not None
    assert out.payload.payload_schema == "agent_13.file_delivery.output"
    assert isinstance(round_trip(out.payload), BundleManifest)
