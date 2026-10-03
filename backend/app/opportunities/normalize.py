import re
import unicodedata
from collections.abc import Iterable

LEGAL_SUFFIXES = frozenset(
    {
        "inc",
        "llc",
        "ltd",
        "limited",
        "corp",
        "corporation",
        "co",
        "gmbh",
        "plc",
        "sa",
        "ag",
        "bv",
        "pvt",
        "private",
    }
)
SKILL_KEY_MAX_CHARS = 40
MAX_SKILL_KEYS = 10
MIN_YEARS_CEILING = 50
DOMAIN_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
URL_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://")
TLD = re.compile(r"^([a-z]{2,63}|xn--[a-z0-9-]{1,59})$")
PORT = re.compile(r":\d{1,5}$")


def collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


def _strip_punctuation(value: str) -> str:
    return "".join(char for char in value if unicodedata.category(char)[0] not in {"P", "S"})


def normalize_text(value: str) -> str:
    folded = unicodedata.normalize("NFKC", value).lower()
    return collapse_whitespace(_strip_punctuation(folded))


def normalize_company_name(name: str) -> str:
    tokens = normalize_text(name).split()
    while len(tokens) > 1 and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def normalize_domain(raw: str) -> str | None:
    value = unicodedata.normalize("NFKC", raw).strip().lower()
    value = URL_SCHEME.sub("", value)
    host = re.split(r"[/?#]", value, maxsplit=1)[0]
    if "@" in host or " " in host:
        return None
    host = PORT.sub("", host).rstrip(".")
    host = host.removeprefix("www.")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    labels = host.split(".")
    if len(host) > 253 or len(labels) < 2:
        return None
    if not all(DOMAIN_LABEL.match(label) for label in labels) or not TLD.match(labels[-1]):
        return None
    return host


def normalize_skill_keys(keys: Iterable[str]) -> list[str]:
    seen: dict[str, None] = {}
    for key in keys:
        cleaned = collapse_whitespace(key).lower()[:SKILL_KEY_MAX_CHARS].strip()
        if cleaned:
            seen.setdefault(cleaned)
    return list(seen)[:MAX_SKILL_KEYS]


def clamp_min_years(value: float | None) -> int | None:
    if value is None or value != value:
        return None
    return max(0, min(MIN_YEARS_CEILING, round(value)))


def clean_note(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "").strip()
    return cleaned or None
