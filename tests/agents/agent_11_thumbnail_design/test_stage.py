"""Stage tests: IT-01.. whole task on fakes."""

from amw_core.contracts.task_output import TaskOutput
from amw_core.enums import CheckVerdict

from tests.agents.agent_11_thumbnail_design.env import make_env


def test_whole_task_education_three_variants() -> None:
    env = make_env()
    out = env.stage.run(env.ti, "att_x")
    assert isinstance(out, TaskOutput)
    assert out.payload is not None and out.payload.data is not None
    d = out.payload.data
    assert d["verdict"] == "ALLOWED"
    print(d["variant_count_produced"], [r.check_id for r in out.validation_results if r.verdict == CheckVerdict.FAIL])
    assert d["variant_count_produced"] == 3
