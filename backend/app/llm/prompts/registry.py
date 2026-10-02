import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from string import Template

from pydantic import BaseModel

from app.db.models import LlmPurpose, LlmTier
from app.llm.errors import PromptMisuse, UnknownPrompt
from app.llm.untrusted import UNTRUSTED_NOTICE, wrap_untrusted


@dataclass(frozen=True)
class RenderedPrompt:
    system: str
    user: str


@dataclass(frozen=True)
class Prompt:
    prompt_id: str
    version: int
    purpose: LlmPurpose
    tier: LlmTier
    system: str
    user: str
    output_schema: type[BaseModel] | None = None
    untrusted_variables: frozenset[str] = field(default_factory=frozenset)

    @property
    def variable_names(self) -> frozenset[str]:
        return frozenset(Template(self.system).get_identifiers()) | frozenset(
            Template(self.user).get_identifiers()
        )

    def content_hash(self) -> str:
        schema = None if self.output_schema is None else self.output_schema.model_json_schema()
        canonical = json.dumps(
            {
                "prompt_id": self.prompt_id,
                "version": self.version,
                "purpose": self.purpose.value,
                "tier": self.tier.value,
                "system": self.system,
                "user": self.user,
                "schema": schema,
                "untrusted": sorted(self.untrusted_variables),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def render(self, variables: Mapping[str, str]) -> RenderedPrompt:
        expected = self.variable_names
        if set(variables) != expected:
            raise PromptMisuse(f"variables must be exactly {sorted(expected)}")
        values = {
            name: wrap_untrusted(name, value) if name in self.untrusted_variables else value
            for name, value in variables.items()
        }
        system = Template(self.system).substitute(values)
        if self.untrusted_variables:
            system = f"{system}\n\n{UNTRUSTED_NOTICE}"
        return RenderedPrompt(system=system, user=Template(self.user).substitute(values))


class PromptRegistry:
    def __init__(self) -> None:
        self._prompts: dict[tuple[str, int], Prompt] = {}

    def register(self, prompt: Prompt) -> Prompt:
        key = (prompt.prompt_id, prompt.version)
        if key in self._prompts:
            raise ValueError(f"duplicate prompt {prompt.prompt_id} v{prompt.version}")
        if prompt.version < 1:
            raise ValueError("prompt version must be at least 1")
        unknown = prompt.untrusted_variables - prompt.variable_names
        if unknown:
            raise ValueError(f"untrusted variables not in templates: {sorted(unknown)}")
        self._prompts[key] = prompt
        return prompt

    def get(self, prompt_id: str, version: int | None = None) -> Prompt:
        versions = [v for (pid, v) in self._prompts if pid == prompt_id]
        if not versions:
            raise UnknownPrompt(prompt_id)
        chosen = max(versions) if version is None else version
        try:
            return self._prompts[(prompt_id, chosen)]
        except KeyError:
            raise UnknownPrompt(f"{prompt_id} v{chosen}") from None

    def all(self) -> list[Prompt]:
        return [self._prompts[key] for key in sorted(self._prompts)]

    def lock_snapshot(self) -> dict[str, dict[str, str]]:
        snapshot: dict[str, dict[str, str]] = {}
        for prompt in self.all():
            snapshot.setdefault(prompt.prompt_id, {})[str(prompt.version)] = prompt.content_hash()
        return snapshot
