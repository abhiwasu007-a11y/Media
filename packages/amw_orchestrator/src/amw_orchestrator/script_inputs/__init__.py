"""Production ``InputResolver`` of agent_05 script drafting and the per-source copyright use."""

from amw_orchestrator.script_inputs.resolver import (
    ChannelFacts,
    ChannelFactsReader,
    ScriptDocumentSource,
    ScriptInputResolver,
    ScriptResolvedInputs,
)
from amw_orchestrator.script_inputs.sources import (
    LibrarySourceClassifier,
    ResolvedSource,
    SourceUse,
)

__all__ = [
    "ChannelFacts",
    "ChannelFactsReader",
    "LibrarySourceClassifier",
    "ResolvedSource",
    "ScriptDocumentSource",
    "ScriptInputResolver",
    "ScriptResolvedInputs",
    "SourceUse",
]
