import json
import sys
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from app.config import Settings
from app.main import create_app


def build_schema() -> dict[str, Any]:
    settings = Settings(database_url=SecretStr("postgresql://schema:schema@localhost/schema"))
    schema: dict[str, Any] = create_app(settings).openapi()
    return schema


def render_schema() -> str:
    return json.dumps(build_schema(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("openapi.json")
    target.write_text(render_schema(), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
