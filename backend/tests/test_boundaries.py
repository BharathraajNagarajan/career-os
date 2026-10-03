import ast
import re
from collections.abc import Iterable
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
TESTS = Path(__file__).resolve().parent
ANTHROPIC_MODULE = APP / "llm" / "providers" / "anthropic.py"

LLM_MODELS = {"LlmRun", "LlmPurpose", "LlmTier", "LlmProviderName", "LlmRunStatus"}
REVIEW_MODELS = {"ReviewItem", "ReviewSource", "ProposalType", "ReviewStatus"}

LLM_ALLOWED = {
    "app.llm",
    "app.config",
    "app.core.logging",
    "app.db.base",
    "app.db.tenancy",
}
REVIEW_ALLOWED = {
    "app.review",
    "app.core.logging",
    "app.db.base",
    "app.db.tenancy",
    "app.db.versioning",
}
ROUTER_ALLOWED = {"app.auth.deps", "app.auth.service", "app.core.errors", "app.config"}


def imported(path: Path) -> list[tuple[str, set[str]]]:
    found: list[tuple[str, set[str]]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.extend((alias.name, set()) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append((node.module, {alias.name for alias in node.names}))
    return found


def is_allowed(module: str, allowed: set[str]) -> bool:
    return any(module == prefix or module.startswith(prefix + ".") for prefix in allowed)


def violations(path: Path, *, allowed: set[str], models: set[str]) -> list[str]:
    bad: list[str] = []
    for module, names in imported(path):
        if module == "app.db.models":
            bad.extend(f"{module}.{name}" for name in sorted(names - models))
        elif module.startswith("app.") and not is_allowed(module, allowed):
            bad.append(module)
    return bad


def python_files(root: Path) -> Iterable[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def test_only_the_anthropic_adapter_imports_the_sdk() -> None:
    offenders = [
        str(path.relative_to(APP.parent))
        for root in (APP, TESTS, APP.parent / "alembic")
        for path in python_files(root)
        if path != ANTHROPIC_MODULE
        and any(module.split(".")[0] == "anthropic" for module, _ in imported(path))
    ]

    assert offenders == []
    assert any(module == "anthropic" for module, _ in imported(ANTHROPIC_MODULE))


def test_gateway_core_cannot_reach_tokens_sessions_credentials_or_other_repositories() -> None:
    core = [path for path in python_files(APP / "llm") if path.name != "router.py"]

    assert core
    for path in core:
        assert violations(path, allowed=LLM_ALLOWED, models=LLM_MODELS) == [], path.name


def test_llm_router_only_adds_http_dependencies() -> None:
    bad = violations(
        APP / "llm" / "router.py", allowed=LLM_ALLOWED | ROUTER_ALLOWED, models=LLM_MODELS
    )

    assert bad == []


def test_review_framework_cannot_reach_domain_tables_or_the_llm_layer() -> None:
    core = [path for path in python_files(APP / "review") if path.name != "router.py"]

    assert core
    for path in core:
        assert violations(path, allowed=REVIEW_ALLOWED, models=REVIEW_MODELS) == [], path.name
    assert (
        violations(
            APP / "review" / "router.py",
            allowed=REVIEW_ALLOWED | ROUTER_ALLOWED,
            models=REVIEW_MODELS,
        )
        == []
    )


def test_the_boundary_checker_detects_forbidden_imports(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "from app.auth.tokens import csrf_token\n"
        "from app.resumes.repository import ResumeRepository\n"
        "from app.db.models import LlmRun, Resume\n"
        "import app.auth.session\n",
        encoding="utf-8",
    )

    assert violations(sample, allowed=LLM_ALLOWED, models=LLM_MODELS) == [
        "app.auth.tokens",
        "app.resumes.repository",
        "app.db.models.Resume",
        "app.auth.session",
    ]


def test_no_model_ids_or_prices_are_hard_coded_in_application_code() -> None:
    model_id = re.compile(r"claude-|haiku|sonnet|opus|fable|mythos|gpt-", re.IGNORECASE)
    offenders = [
        str(path.relative_to(APP))
        for path in python_files(APP)
        if model_id.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == []
