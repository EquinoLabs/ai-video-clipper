"""Security utilities: path sanitization, ID generation, and ownership guards."""

import os
import re
import uuid
from pathlib import Path


def generate_id(prefix: str = "") -> str:
    """Generate a clean UUIDv4, optionally prefixed."""
    uid = str(uuid.uuid4())
    return f"{prefix}_{uid}" if prefix else uid


def sanitize_filename(filename: str) -> str:
    """Sanitize user-provided filename, stripping directory traversal and unsafe characters."""
    # Strip any leading directory components
    clean_name = os.path.basename(filename)
    # Allow alphanumeric, dashes, underscores, and dots only
    clean_name = re.sub(r"[^a-zA-Z0-9._-]", "_", clean_name)
    return clean_name or "unnamed_media"


def safe_join_path(base_dir: Path, untrusted_subpath: str) -> Path:
    """Safely resolve an untrusted subpath inside base_dir, preventing directory traversal."""
    resolved = (base_dir / untrusted_subpath).resolve()
    base_resolved = base_dir.resolve()
    if not str(resolved).startswith(str(base_resolved)):
        raise ValueError(f"Path traversal detected for subpath: {untrusted_subpath}")
    return resolved
