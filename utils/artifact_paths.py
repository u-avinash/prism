"""Safe resolution helpers for Prism-generated incident artifacts."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from config.settings import get_settings


_ARTIFACT_CONFIG = {
    "pdf": ("pdf_output_dir", (".pdf",)),
    "patch": ("patch_output_dir", (".patch", ".diff", ".txt", ".md")),
}


def managed_artifact_path(
    path_value: Optional[str],
    kind: str,
    *,
    must_exist: bool = True,
) -> Optional[Path]:
    """
    Resolve an artifact only when it resides beneath Prism's configured output
    directory and has an approved suffix. Symlink and traversal escapes fail.
    """
    config = _ARTIFACT_CONFIG.get(kind)
    if not path_value or not config:
        return None

    setting_name, allowed_suffixes = config
    root_value = getattr(get_settings(), setting_name, None)
    if not root_value:
        return None

    try:
        root = Path(root_value).expanduser().resolve()
        candidate = Path(path_value).expanduser().resolve()
        candidate.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None

    if candidate.suffix.lower() not in allowed_suffixes:
        return None
    if must_exist and (not candidate.exists() or not candidate.is_file()):
        return None
    return candidate


def managed_artifact_paths(
    values: Iterable[Optional[str]],
    kind: str,
) -> list[Path]:
    """Return unique, existing safe artifact paths from persisted values."""
    resolved: list[Path] = []
    seen: set[Path] = set()
    for value in values:
        path = managed_artifact_path(value, kind)
        if path and path not in seen:
            seen.add(path)
            resolved.append(path)
    return resolved
