"""Filesystem anchors for the project.

Every configurable path in the app is expressed relative to the project root so
that the application behaves identically regardless of the working directory it
was launched from.
"""

from pathlib import Path

# backend/app/core/paths.py -> backend/app/core -> backend/app -> backend -> <root>
PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]

DATA_DIR: Path = PROJECT_ROOT / "data"
SAMPLE_DIR: Path = DATA_DIR / "sample"
SECRETS_DIR: Path = DATA_DIR / "secrets"


def resolve(path: str | Path) -> Path:
    """Resolve a possibly-relative configured path against the project root."""
    candidate = Path(path)
    return candidate if candidate.is_absolute() else (PROJECT_ROOT / candidate)
