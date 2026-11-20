"""The job request of ``run_job``: ids of an EXISTING tenant, the owner topic and the knowledge
library reference (repo path + commit SHA only; the book text is never copied, never logged).

There is no field for the run mode, for ``real_run`` or for a provider: ``extra="forbid"`` refuses
them. The mode comes from the runtime configuration alone (CCR-273 / D10 fail closed)."""

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from amw_core.contracts import OwnerTopic
from amw_core.enums import ProductionTypeKey
from amw_core.errors import InputInvalidError
from amw_runtime.confirmations import ConfirmationRecord

_MAX_FIELDS_SHOWN = 20
_SHA = re.compile(r"^[0-9a-f]{40}$")


class LibraryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_path: Path
    commit_sha: str

    @field_validator("commit_sha")
    @classmethod
    def _sha(cls, value: str) -> str:
        if _SHA.fullmatch(value) is None:
            raise ValueError("commit_sha must be 40 lowercase hex characters")
        return value


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    org_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    channel_id: str = Field(min_length=1)
    topic: OwnerTopic
    library: LibraryInput
    production_type: ProductionTypeKey = ProductionTypeKey.CHANNEL_LONG_FORM
    confirmations: tuple[ConfirmationRecord, ...] = ()
    """Owner confirmations (provider limits ...) with the IDs of their evidence rows; the preflight
    of a real run checks each against the evidence store, none is trusted."""


def load_request(path: Path) -> JobRequest:
    """Parse the request file; a bad file is ``INPUT_INVALID`` naming fields, never values."""
    try:
        return JobRequest.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError:
        raise InputInvalidError("the job request file cannot be read") from None
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})
        raise InputInvalidError(
            "the job request is invalid", details={"fields": fields[:_MAX_FIELDS_SHOWN]}
        ) from None
