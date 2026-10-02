from collections.abc import Collection

from pydantic import BaseModel, ConfigDict, Field

OUTLINE_SCHEMA_VERSION = 1
MAX_SECTIONS = 50
MAX_HEADING_CHARS = 80
MAX_HEADING_WORDS = 4

SECTION_WORDS = frozenset(
    {
        "summary",
        "profile",
        "objective",
        "experience",
        "work experience",
        "professional experience",
        "employment",
        "employment history",
        "education",
        "skills",
        "technical skills",
        "projects",
        "certifications",
        "awards",
        "publications",
        "languages",
        "interests",
        "volunteering",
        "references",
    }
)


class OutlineSection(BaseModel):
    model_config = ConfigDict(frozen=True)

    heading: str = Field(max_length=MAX_HEADING_CHARS)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)


class ParsedOutline(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = OUTLINE_SCHEMA_VERSION
    line_count: int = Field(ge=0)
    char_count: int = Field(ge=0)
    sections: list[OutlineSection] = Field(default_factory=list, max_length=MAX_SECTIONS)


def looks_like_heading(line: str) -> bool:
    if len(line) > MAX_HEADING_CHARS or len(line.split()) > MAX_HEADING_WORDS:
        return False
    if line.endswith(":"):
        return len(line) > 1
    letters = [char for char in line if char.isalpha()]
    if len(letters) >= 3 and line.upper() == line:
        return True
    return line.lower().rstrip(":") in SECTION_WORDS


def build_outline(text: str, styled_headings: Collection[str] = ()) -> ParsedOutline:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    styled = set(styled_headings)
    starts = [
        number
        for number, line in enumerate(lines, start=1)
        if line[:MAX_HEADING_CHARS] in styled or looks_like_heading(line)
    ][:MAX_SECTIONS]
    sections = [
        OutlineSection(
            heading=lines[start - 1][:MAX_HEADING_CHARS],
            start_line=start,
            end_line=(starts[index + 1] - 1) if index + 1 < len(starts) else len(lines),
        )
        for index, start in enumerate(starts)
    ]
    return ParsedOutline(line_count=len(lines), char_count=len(text), sections=sections)
