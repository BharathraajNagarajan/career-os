from pydantic import BaseModel, Field

from app.db.models import LlmPurpose, LlmTier
from app.llm.prompts.evidence_extract import (
    EVIDENCE_EXTRACT,
    EVIDENCE_EXTRACT_SYSTEM,
    EVIDENCE_EXTRACT_USER,
    EvidenceExtraction,
)
from app.llm.prompts.jd_extract import (
    JD_EXTRACT,
    JD_EXTRACT_SYSTEM,
    JD_EXTRACT_USER,
    JdExtraction,
)
from app.llm.prompts.registry import Prompt, PromptRegistry

SELFTEST_STRUCTURED = "selftest.note_tone"
SELFTEST_STREAM = "selftest.reply"


class NoteTone(BaseModel):
    tone: str = Field(pattern="^(positive|neutral|negative)$")
    summary: str = Field(max_length=200)


def default_registry() -> PromptRegistry:
    registry = PromptRegistry()
    registry.register(
        Prompt(
            prompt_id=SELFTEST_STRUCTURED,
            version=1,
            purpose=LlmPurpose.CLASSIFY_EMAIL,
            tier=LlmTier.FAST,
            system=(
                "You label the tone of a short synthetic note. "
                "Reply with JSON containing a tone and a one-sentence summary."
            ),
            user="Note:\n$note",
            output_schema=NoteTone,
            untrusted_variables=frozenset({"note"}),
        )
    )
    registry.register(
        Prompt(
            prompt_id=SELFTEST_STREAM,
            version=1,
            purpose=LlmPurpose.CHAT,
            tier=LlmTier.FAST,
            system="You answer briefly and politely.",
            user="$question",
        )
    )
    registry.register(
        Prompt(
            prompt_id=JD_EXTRACT,
            version=1,
            purpose=LlmPurpose.EXTRACT_JD,
            tier=LlmTier.FAST,
            system=JD_EXTRACT_SYSTEM,
            user=JD_EXTRACT_USER,
            output_schema=JdExtraction,
            untrusted_variables=frozenset({"jd"}),
        )
    )
    registry.register(
        Prompt(
            prompt_id=EVIDENCE_EXTRACT,
            version=1,
            purpose=LlmPurpose.EXTRACT_RESUME,
            tier=LlmTier.FAST,
            system=EVIDENCE_EXTRACT_SYSTEM,
            user=EVIDENCE_EXTRACT_USER,
            output_schema=EvidenceExtraction,
            untrusted_variables=frozenset({"resume"}),
        )
    )
    return registry
