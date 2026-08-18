"""Prompt loading.

Prompts live in `.md` files rather than inline strings so they can be read,
diffed and revised by someone who is tuning the system's behaviour without
touching Python. Placeholders use `$name` (string.Template) because the prompts
contain JSON braces that `str.format` would choke on.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from string import Template

PROMPT_DIR = Path(__file__).parent


@lru_cache(maxsize=32)
def load(name: str) -> str:
    """Read a prompt file by stem, e.g. `load("classify")`."""
    path = PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def render(name: str, **values: object) -> str:
    """Load a prompt and substitute `$placeholders`.

    `safe_substitute` is used on purpose: an unfilled placeholder should show up
    in the prompt for a human to notice, not raise at request time.
    """
    return Template(load(name)).safe_substitute(**values)
