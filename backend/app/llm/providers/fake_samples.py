import re
from typing import Any

from app.llm.providers.base import ProviderRequest

RESUME_BLOCK = re.compile(
    r'<untrusted_content label="resume">\n(.*?)\n</untrusted_content>', re.DOTALL
)
MIN_LINE_CHARS = 30
MAX_LINE_CHARS = 300
MAX_CLAIMS = 5


def _lines(request: ProviderRequest) -> list[str]:
    block = RESUME_BLOCK.search(request.user)
    text = "" if block is None else block.group(1)
    return [" ".join(line.split()) for line in text.splitlines()]


def evidence_extraction_sample(request: ProviderRequest) -> dict[str, Any]:
    lines = _lines(request)
    skills: list[str] = []
    for index, line in enumerate(lines[:-1]):
        if line.lower().endswith("skills:") or line.lower().startswith("skills:"):
            skills = [name.strip() for name in lines[index + 1].split(",") if name.strip()]
            break
    usable = [line for line in lines if MIN_LINE_CHARS <= len(line) <= MAX_LINE_CHARS]
    claims = [
        {
            "statement": line,
            "evidence_class": "professional" if position == 0 else "project",
            "engagement_type": "unspecified",
            "engagement_quote": None,
            "organization": None,
            "start_date": None,
            "end_date": None,
            "skills": skills[:2] if position == 0 else [],
            "confidence": 0.6,
            "rationale": "Synthetic placeholder from the fake provider",
        }
        for position, line in enumerate(usable[:MAX_CLAIMS])
    ]
    return {
        "claims": claims,
        "skills": [
            {"name": name, "confidence": 0.6, "rationale": "Synthetic placeholder"}
            for name in skills
        ],
    }
