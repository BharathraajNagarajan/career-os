import json
import sys
from pathlib import Path

from app.llm.prompts.catalog import default_registry

LOCK_PATH = Path(__file__).with_name("prompts.lock.json")


def render_lock() -> str:
    return json.dumps(default_registry().lock_snapshot(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    LOCK_PATH.write_text(render_lock(), encoding="utf-8", newline="\n")
    sys.stdout.write(f"wrote {LOCK_PATH.name}\n")
