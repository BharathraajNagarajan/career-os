from pydantic import BaseModel, Field

from app.db.models import LlmPurpose, LlmTier
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
    return registry
