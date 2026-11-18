# Rubric — `agent_16/compliance_gate.v1` evaluation judge

Integer 1–5 per criterion. The judge sees the case input, the model output and the expected object. It never decides the verdict (assertion A4 is deterministic).

| Criterion | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| **J1 Rationale quality** | names the rule and the exact reason in plain words; correct reading of tense, frame and purpose (IN-03 two-part test) | correct and clear, minor vagueness | correct but generic ("violates rule") | partly wrong reasoning though the finding is right | wrong reasoning or reasoning that would mislead a reviewer |
| **J2 Quote precision** | shortest span that shows the problem, nothing extra | short span with a few extra words | whole sentence where a phrase suffices | quote misses the decisive words | quote does not show the problem (or null where required) |

Anchors for hard negatives: a `NO_VIOLATION` rationale scores 5 on J1 only when it says *why* the text is education (definition, past tense, labelled hypothetical, quoted rule, own course). J2 is not scored for `NO_VIOLATION` findings (quote null).
