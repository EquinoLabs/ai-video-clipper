"""Short-clip input package validation models and utilities."""

import logging
from pathlib import Path
from typing import NamedTuple, Optional
from pydantic import BaseModel, Field

from app.domain.manifest.models import ClipMetadata
from app.domain.transcript.models import TranscriptArtifact

logger = logging.getLogger(__name__)


class LongMasterPackageError(ValueError):
    """Raised when a long-master package folder fails structural or content validation."""
    pass


class LongMasterPackage(NamedTuple):
    """Resolved and validated long-master package contents."""
    package_dir: Path
    clean_master_path: Path
    transcript_path: Path
    metadata_path: Path
    metadata: ClipMetadata
    transcript: TranscriptArtifact


def validate_long_master_package(package_dir: Path) -> LongMasterPackage:
    """Validate and load an existing long-master clip folder.

    Rules:
    1. Folder must exist and be a directory.
    2. Must contain metadata.json which parses into a valid ClipMetadata with clip_type='long'.
    3. Must contain transcript.json which parses into a valid TranscriptArtifact.
    4. Must contain the clean master video file specified in metadata.files.clean_master (or clip_XX.mp4).
    5. Clean master video file must not be empty (size > 0).
    6. Ensures the package is NOT a short clip (prevents recursive short-of-short discovery).
    """
    p_dir = Path(package_dir).resolve()
    if not p_dir.exists():
        raise LongMasterPackageError(f"Long-master package directory does not exist: {p_dir}")
    if not p_dir.is_dir():
        raise LongMasterPackageError(f"Long-master package path is not a directory: {p_dir}")

    # 1. Validate metadata.json
    meta_path = p_dir / "metadata.json"
    if not meta_path.exists() or not meta_path.is_file():
        raise LongMasterPackageError(
            f"Missing required 'metadata.json' in long-master package: {p_dir}"
        )

    try:
        metadata = ClipMetadata.model_validate_json(meta_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise LongMasterPackageError(
            f"Failed to parse 'metadata.json' in {p_dir}: {exc}"
        ) from exc

    # Enforce hierarchy: must be a long clip, not short
    if metadata.clip_type != "long":
        raise LongMasterPackageError(
            f"Expected long clip package (clip_type='long'), but found clip_type='{metadata.clip_type}' in {meta_path}. "
            "Recursive short-of-short discovery is strictly prohibited."
        )

    # 2. Validate clean master video file
    clean_master_name = metadata.files.clean_master
    if not clean_master_name:
        # Fallback inspection: look for clip_*.mp4 that is not _final.mp4
        mp4_candidates = [
            f for f in p_dir.glob("*.mp4")
            if not f.name.endswith("_final.mp4") and not ".rendering." in f.name
        ]
        if mp4_candidates:
            clean_master_name = mp4_candidates[0].name
        else:
            raise LongMasterPackageError(
                f"metadata.json in {p_dir} does not specify files.clean_master, and no clean mp4 master was found."
            )

    clean_master_path = p_dir / clean_master_name
    if not clean_master_path.exists() or not clean_master_path.is_file():
        raise LongMasterPackageError(
            f"Clean master video file not found: {clean_master_path}"
        )
    if clean_master_path.stat().st_size == 0:
        raise LongMasterPackageError(
            f"Clean master video file is empty (0 bytes): {clean_master_path}"
        )

    # 3. Validate transcript.json
    trans_name = metadata.files.transcript or "transcript.json"
    trans_path = p_dir / trans_name
    if not trans_path.exists() or not trans_path.is_file():
        raise LongMasterPackageError(
            f"Long-master transcript file not found: {trans_path}"
        )

    try:
        transcript = TranscriptArtifact.model_validate_json(trans_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise LongMasterPackageError(
            f"Failed to parse 'transcript.json' in {p_dir}: {exc}"
        ) from exc

    if not transcript.segments:
        logger.warning(f"Long-master transcript in {p_dir} contains zero segments.")

    return LongMasterPackage(
        package_dir=p_dir,
        clean_master_path=clean_master_path,
        transcript_path=trans_path,
        metadata_path=meta_path,
        metadata=metadata,
        transcript=transcript,
    )
