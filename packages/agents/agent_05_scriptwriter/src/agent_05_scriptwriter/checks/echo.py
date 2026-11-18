"""``EchoGuard`` (blueprint 19.1 control 2): output that repeats a prompt sentence or a refused
instruction is a failed check. Instruction-like text in the inputs is data, never repeated."""

from collections.abc import Iterable, Sequence

from agent_05_scriptwriter.checks.results import CheckResult, failed, passed
from agent_05_scriptwriter.text import normalise, split_sentences

PROMPT_MIN_WORDS = 6
INSTRUCTION_MIN_WORDS = 4


class EchoGuard:
    def __init__(self, prompt_text: str, instructions: Sequence[str] = ()) -> None:
        sentences: set[str] = set()
        for line in prompt_text.splitlines():
            for sentence in split_sentences(line):
                norm = normalise(sentence)
                if len(norm.split()) >= PROMPT_MIN_WORDS:
                    sentences.add(norm)
        self._prompt = sentences
        self._instructions = {
            n for i in instructions if len((n := normalise(i)).split()) >= INSTRUCTION_MIN_WORDS
        }

    def echoes(self, text: str) -> bool:
        norm = normalise(text)
        return any(p in norm for p in self._prompt) or any(i in norm for i in self._instructions)

    def check(self, check_id: str, texts: Iterable[str]) -> CheckResult:
        if any(self.echoes(t) for t in texts):
            return failed(check_id, "output repeats a prompt sentence or an input instruction")
        return passed(check_id, "no prompt or instruction echo")
