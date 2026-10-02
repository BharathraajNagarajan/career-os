class LlmError(Exception):
    code = "llm_error"

    def __init__(self, detail: str = "") -> None:
        super().__init__(detail or self.code)


class LlmBudgetExhausted(LlmError):
    code = "llm_budget_exhausted"


class LlmOutputInvalid(LlmError):
    code = "llm_output_invalid"


class LlmProviderError(LlmError):
    code = "llm_provider_error"

    def __init__(self, provider_code: str) -> None:
        super().__init__(provider_code)
        self.provider_code = provider_code


class UnknownPrompt(LookupError):
    pass


class PromptMisuse(ValueError):
    pass
