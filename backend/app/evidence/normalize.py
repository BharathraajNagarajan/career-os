import unicodedata
from collections.abc import Iterable

from app.opportunities.normalize import collapse_whitespace

SKILL_NAME_MAX_CHARS = 100
MAX_ALIASES = 50
EDGE_PUNCTUATION = ".,;:!?\"'()[]{}"
SEPARATORS = str.maketrans({"-": " ", "_": " "})


def clean_name(value: str) -> str:
    return collapse_whitespace(unicodedata.normalize("NFKC", value))[:SKILL_NAME_MAX_CHARS].strip()


def skill_key(value: str) -> str:
    folded = unicodedata.normalize("NFKC", value).casefold().translate(SEPARATORS)
    return collapse_whitespace(folded).strip(EDGE_PUNCTUATION).strip()


def clean_aliases(aliases: Iterable[str], *, canonical_name: str) -> list[str]:
    seen = {skill_key(canonical_name)}
    cleaned: list[str] = []
    for alias in aliases:
        name = clean_name(alias)
        key = skill_key(name)
        if key and key not in seen:
            seen.add(key)
            cleaned.append(name)
    return cleaned


def skill_keys(canonical_name: str, aliases: Iterable[str]) -> set[str]:
    return {key for key in (skill_key(canonical_name), *map(skill_key, aliases)) if key}
