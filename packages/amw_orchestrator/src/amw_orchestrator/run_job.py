"""``run_job``: command line entry of the 3A graph runner (``python -m amw_orchestrator.run_job``).

    run_job --request <job.json> [--run-entry-config <file>]

The run mode is the runtime configuration's (``AMW_RUNTIME_MODE``, no default: unset is refused)
and nothing on the command line or in the request can change it. Exit codes: 0 delivered or
waiting for the owner's decision, 1 the job stopped, 2 refused before any work (configuration,
request or preflight; every unmet item is listed). The report is plain text: the first stage that
did not complete and why, and names only (never a secret value)."""

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TextIO

from amw_core.config import load_settings
from amw_core.contracts import Stage
from amw_core.enums import TaskState
from amw_core.errors import AmwError
from amw_orchestrator.composition import Composition, RealRunWiring, compose
from amw_orchestrator.driver import RunReport
from amw_orchestrator.plumbing import BANNER
from amw_orchestrator.run_request import JobRequest, load_request
from amw_orchestrator.run_settings import load_run_entry_settings
from amw_runtime.config import load_runtime_config
from amw_runtime.errors import PreflightRefused

EXIT_OK, EXIT_STOPPED, EXIT_REFUSED = 0, 1, 2
_APPROVAL_TASK_TYPE = "svc_s07.request_approval"
_SECRETISH = ("SECRET", "API_KEY", "TOKEN", "PASSWORD", "DATABASE")
_MIN_SCRUB = 6
_MAX_ERROR_CHARS = 300


def execute(comp: Composition) -> RunReport:
    """Start (or resume) the job and run it. In a DRY_RUN the test desk decides the approval and the
    run continues; in a real run the process stops at ``AWAITING_APPROVAL``: only the owner's chat
    decision (R14 evidence) resumes it, on the next call."""
    if comp.resume:
        report = comp.runner.load(comp.job, comp.graph)
    else:
        report = comp.runner.start(comp.job, comp.graph)
    report = comp.runner.run(comp.job, comp.graph, report)
    if comp.desk is not None and report.status == "AWAITING_APPROVAL":
        approval_stages = {s.stage_id for s in comp.graph if s.task_type == _APPROVAL_TASK_TYPE}
        for run in report.stages.values():
            if run.stage_id in approval_stages and run.state is not TaskState.COMPLETED:
                comp.desk.decide(run.task_id)
        report = comp.runner.run(comp.job, comp.graph, report)
    return report


def scrub(text: str, env: Mapping[str, str], extra: Sequence[str] = ()) -> str:
    """No value of a secret-looking variable (or ``extra``) can reach the output."""
    values = [v for k, v in env.items() if any(w in k.upper() for w in _SECRETISH)]
    for value in sorted({*values, *extra}, key=len, reverse=True):
        if len(value) >= _MIN_SCRUB:
            text = text.replace(value, "<redacted>")
    return text


def _first_unfinished(report: RunReport, graph: Sequence[Stage]) -> str:
    """The first stage of the graph (topological order) that did not complete, and why."""
    for stage in graph:
        run = report.stages.get(stage.stage_id)
        if run is None:
            return f"{stage.stage_id} (not started)"
        if run.state is TaskState.COMPLETED:
            continue
        err = run.output.error if run.output is not None else None
        why = (
            f"{err.code}: {err.message}"[:_MAX_ERROR_CHARS] if err is not None else run.state.value
        )
        return f"{run.stage_id} ({run.state.value}) {why}"
    return "none"


def format_report(comp: Composition, report: RunReport, request: JobRequest) -> str:
    lines = [
        "AMW run_job report",
        f"mode: {comp.mode.value} (real_run={comp.real_run})",
    ]
    if not comp.real_run:
        lines.append(BANNER)
    lines += [
        f"job: {report.job_id}",
        f"library: commit {request.library.commit_sha} ({request.library.repo_path.name})",
        f"status: {report.status}",
        f"detail: {report.detail}" if report.detail else "detail: -",
        f"first stage not completed: {_first_unfinished(report, comp.graph)}",
        "stages:",
    ]
    for sid in report.order:
        run = report.stages.get(sid)
        if run is not None:
            lines.append(f"  {sid}: {run.state.value}")
    lines += [f"note: {n}" for n in comp.notes]
    return "\n".join(lines)


def format_refusal(exc: PreflightRefused) -> str:
    lines = [f"REFUSED before start: {len(exc.items)} unmet item(s), nothing was run"]
    lines += [f"  - {i.code}: {i.message}" for i in exc.items]
    return "\n".join(lines)


def main(
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
    *,
    out: TextIO | None = None,
    real_wiring: RealRunWiring | None = None,
    **inject: Any,
) -> int:
    """``inject`` (``evidence_factory``, ``transports``, ``clock``, ``scratch``) is for tests; the
    command line has no way to pass it."""
    stream = out or sys.stdout
    environ: Mapping[str, str] = dict(os.environ) if env is None else env
    parser = argparse.ArgumentParser(prog="run_job", description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--run-entry-config", type=Path, default=None)
    args = parser.parse_args(argv)
    extra: list[str] = []
    try:
        config = load_runtime_config(environ)
        settings = load_settings(environ=environ)
        if settings.database.url is not None:
            extra.append(settings.database.url.get_secret_value())
        request = load_request(args.request)
        comp = compose(
            request, config=config, settings=settings,
            run=load_run_entry_settings(args.run_entry_config), env=environ,
            real_wiring=real_wiring, **inject,
        )  # fmt: skip
        report = execute(comp)
    except PreflightRefused as exc:
        print(scrub(format_refusal(exc), environ, extra), file=stream)
        return EXIT_REFUSED
    except AmwError as exc:
        text = f"REFUSED before start: {exc.code}: {exc.message}"
        unmet = exc.details.get("unmet")
        if unmet:
            text += f" (unmet: {', '.join(str(u) for u in unmet)})"
        print(scrub(text, environ, extra), file=stream)
        return EXIT_REFUSED
    except Exception as exc:  # last resort: the type only, never a message that could hold a value
        print(
            scrub(f"FAILED unexpectedly ({type(exc).__name__}); details withheld", environ, extra),
            file=stream,
        )
        return EXIT_STOPPED
    print(scrub(format_report(comp, report, request), environ, extra), file=stream)
    return EXIT_OK if report.status in {"DELIVERED", "AWAITING_APPROVAL"} else EXIT_STOPPED


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
