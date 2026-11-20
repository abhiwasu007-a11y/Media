"""Operator command: build or verify the private library chunk index (development environment).

    python -m amw_orchestrator.library_index build  --config C --library PATH --commit SHA \
        --org-id ORG --collection-id COL
    python -m amw_orchestrator.library_index verify --config C ... (same arguments)

``--config`` is a JSON file OUTSIDE the repository: ``index_dir`` (private directory outside git),
``max_file_bytes``, ``allowed_suffixes`` and ``git_timeout_seconds`` (the reader limits have no
default, CCR-291, D16). Output is COUNTS only: no path, locator, hash or text is printed.
Exit codes: 0 done, 2 refused (typed error, its code is printed)."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_06_fact_checker.library.reader import CheckoutLibraryReader, LibraryLimits, LibraryRef
from amw_core.errors import AmwError, ConfigInvalidError
from amw_orchestrator.library_index.build import build_index
from amw_orchestrator.library_index.loader import PrivateChunkIndex
from amw_orchestrator.library_index.store import check_private_dir


class IndexConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    index_dir: Path
    max_file_bytes: int = Field(ge=1)
    allowed_suffixes: frozenset[str] = Field(min_length=1)
    git_timeout_seconds: float = Field(gt=0)

    def limits(self) -> LibraryLimits:
        return LibraryLimits(
            self.max_file_bytes, self.allowed_suffixes, git_timeout_seconds=self.git_timeout_seconds
        )


def load_config(path: Path) -> IndexConfig:
    try:
        return IndexConfig.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError, ValidationError:
        raise ConfigInvalidError("the index config file is missing or invalid") from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="library_index", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--config", type=Path, required=True)
        p.add_argument("--library", type=Path, required=True)
        p.add_argument("--commit", required=True)
        p.add_argument("--org-id", required=True)
        p.add_argument("--collection-id", required=True)
    return parser


def run(argv: Sequence[str]) -> dict[str, int]:
    args = _parser().parse_args(argv)
    config = load_config(args.config)
    if args.command == "build":
        report = build_index(
            library_root=args.library,
            commit_sha=args.commit,
            org_id=args.org_id,
            collection_id=args.collection_id,
            index_dir=config.index_dir,
            limits=config.limits(),
        )
        return {
            "files_seen": report.files_seen,
            "files_indexed": report.files_indexed,
            "files_without_sections": report.files_without_sections,
            "chunks": report.chunks,
            "ambiguous_locators": report.ambiguous_locators,
        }
    private = check_private_dir(config.index_dir, args.library)
    index = PrivateChunkIndex.load(
        private, org_id=args.org_id, collection_id=args.collection_id, commit_sha=args.commit
    )
    library = CheckoutLibraryReader(LibraryRef(args.library, args.commit), config.limits())
    return {"chunks_checked": index.verify_against_library(library)}


def main(argv: Sequence[str] | None = None) -> int:
    try:
        counts = run(sys.argv[1:] if argv is None else argv)
    except AmwError as exc:
        print(json.dumps({"refused": exc.code}), file=sys.stderr)
        return 2
    print(json.dumps(counts, sort_keys=True))
    return 0
