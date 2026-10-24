"""Input staging service.

Safely stages original videos from init_input/ (or user-specified directories)
into the managed input/ hierarchy with collision-safe filenames, hash generation,
and ingestion metadata tracking.
"""

import datetime
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import NamedTuple, Optional, Set, Tuple

from app.domain.ingestion.models import IngestionMetadata
from app.services.media.probing import MediaProbeError, MediaProbeResult, probe_media_file
from app.services.storage.ingestion import (
    IST,
    compute_file_sha256,
    generate_stable_video_id,
    generate_video_id,
    ingest_source_video,
    load_ingestion_metadata,
    normalize_filename,
    resolve_unique_input_path,
    save_ingestion_metadata,
)

logger = logging.getLogger(__name__)

SUPPORTED_VIDEO_EXTENSIONS: Set[str] = {
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
    ".avi",
    ".m4v",
}


def find_existing_staged_record(
    input_root_dir: Path,
    content_hash: str,
) -> Optional[Tuple[Path, IngestionMetadata]]:
    """Search input_root_dir across all date directories for an existing staged record matching content_hash.

    Verifies the metadata and validates the on-disk file hash before returning.
    Returns (staged_video_path, IngestionMetadata) if a valid record is found, else None.
    """
    if not input_root_dir.exists() or not input_root_dir.is_dir():
        return None

    target_hash = content_hash.strip().lower()

    # Search for all metadata.json files in input/ hierarchy
    for meta_file in input_root_dir.rglob("metadata.json"):
        if not meta_file.is_file():
            continue
        try:
            meta = load_ingestion_metadata(meta_file)
        except Exception as exc:
            logger.warning("Skipping corrupted or unreadable metadata at '%s': %s", meta_file, exc)
            continue

        parent_dir = meta_file.parent
        # Candidate staged file
        candidate_file: Optional[Path] = None
        if meta.stored_filename and (parent_dir / meta.stored_filename).is_file():
            candidate_file = parent_dir / meta.stored_filename
        else:
            # Fallback: look for video files inside this folder
            for sibling in parent_dir.iterdir():
                if is_supported_video_file(sibling):
                    candidate_file = sibling
                    break

        if not candidate_file or not candidate_file.is_file():
            logger.warning("Metadata at '%s' has missing staged media file.", meta_file)
            continue

        # Check recorded hash or compute direct hash if metadata lacks it
        recorded_hash = (meta.content_sha256 or "").strip().lower()
        if recorded_hash == target_hash:
            # Authoritative check: verify on-disk file size and hash
            try:
                actual_hash = compute_file_sha256(candidate_file)
                if actual_hash.lower() == target_hash:
                    return candidate_file, meta
                else:
                    logger.warning(
                        "Staged video at '%s' content hash mismatch (metadata=%s, actual=%s). Not reusing.",
                        candidate_file,
                        recorded_hash,
                        actual_hash,
                    )
            except Exception as read_exc:
                logger.warning("Error verifying file hash for '%s': %s", candidate_file, read_exc)
        elif not recorded_hash:
            # Old metadata lacked content_sha256: verify directly
            try:
                actual_hash = compute_file_sha256(candidate_file)
                if actual_hash.lower() == target_hash:
                    return candidate_file, meta
            except Exception:
                pass

    return None


class StagedInputResult(NamedTuple):
    """Result of staging a source video file."""
    is_staged: bool
    source_path: Path
    staged_path: Optional[Path]
    metadata: Optional[IngestionMetadata]
    error_message: Optional[str] = None


def is_supported_video_file(path: Path) -> bool:
    """Check if file has a supported video extension and is a regular file."""
    p = Path(path)
    return p.is_file() and p.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS


def discover_video_files_in_folder(folder_path: Path) -> list[Path]:
    """Discover all supported video files in a folder or nested hierarchy.
    
    Rules:
    - Recursively traverses if nested directories exist, or lists flat directory.
    - Filters only supported video extensions.
    - Explicitly ignores metadata files (e.g. metadata.json, *__metadata.json) and temporary staging files.
    - Returns unique, deterministically sorted list of Path objects.
    """
    p = Path(folder_path).resolve()
    if not p.exists() or not p.is_dir():
        return []

    discovered: Set[Path] = set()

    for item in p.rglob("*"):
        if not item.is_file():
            continue
        # Ignore temporary staging files or hidden files
        if item.name.startswith(".") or item.name.startswith("~"):
            continue
        # Ignore metadata JSON files
        if item.name.endswith(".json"):
            continue
        if is_supported_video_file(item):
            discovered.add(item.resolve())

    return sorted(list(discovered), key=lambda x: str(x).lower())


def stage_input_video(
    source_file_path: Path,
    input_root: Path = Path("input"),
) -> StagedInputResult:
    """Validate and atomically stage a source video into the input/ directory.

    Rules:
    - Original file is never moved, renamed, or modified.
    - Existing files in input/ are never overwritten; collision-safe filenames are assigned.
    - Atomic staging via temporary file prevents incomplete copies from being picked up.
    - Media probing verifies that the file contains a decodable video stream.
    """
    src = Path(source_file_path).resolve()

    # 1. Basic path validation
    if not src.exists():
        return StagedInputResult(
            is_staged=False,
            source_path=src,
            staged_path=None,
            metadata=None,
            error_message=f"Source file does not exist: {src}",
        )
    if not src.is_file():
        return StagedInputResult(
            is_staged=False,
            source_path=src,
            staged_path=None,
            metadata=None,
            error_message=f"Source path is not a regular file: {src}",
        )
    if not is_supported_video_file(src):
        return StagedInputResult(
            is_staged=False,
            source_path=src,
            staged_path=None,
            metadata=None,
            error_message=f"Unsupported video extension: {src.suffix} (supported: {', '.join(sorted(SUPPORTED_VIDEO_EXTENSIONS))})",
        )
    if src.stat().st_size == 0:
        return StagedInputResult(
            is_staged=False,
            source_path=src,
            staged_path=None,
            metadata=None,
            error_message="Source file is empty (0 bytes)",
        )

    # 2. Probe source file to verify media streams
    try:
        probe_res = probe_media_file(src)
        if not probe_res.video_streams:
            return StagedInputResult(
                is_staged=False,
                source_path=src,
                staged_path=None,
                metadata=None,
                error_message="Source media contains no valid video streams",
            )
    except Exception as exc:
        return StagedInputResult(
            is_staged=False,
            source_path=src,
            staged_path=None,
            metadata=None,
            error_message=f"Media probing failed: {exc}",
        )

    # 3. Compute hash and video identity upfront to check for duplicates and determine layout
    content_hash = compute_file_sha256(src)
    input_root_dir = Path(input_root).resolve()

    # Global duplicate check: Search across all date directories for identical content
    existing_record = find_existing_staged_record(input_root_dir, content_hash)
    if existing_record:
        staged_path, existing_meta = existing_record
        logger.info(
            "Source video '%s' matches existing staged record at '%s' (video_id=%s). Reusing.",
            src.name,
            staged_path,
            existing_meta.video_id,
        )
        return StagedInputResult(
            is_staged=True,
            source_path=src,
            staged_path=staged_path,
            metadata=existing_meta,
            error_message=None,
        )

    # Use stable, date-independent video_id
    video_id = generate_stable_video_id(content_hash)
    now_ist = datetime.datetime.now(IST)
    ingestion_date_str = now_ist.strftime("%Y-%m-%d")
    ingested_at_iso = now_ist.isoformat()

    # Target directory structure: input/YYYY-MM-DD/<stable_video_id>/
    target_video_dir = input_root_dir / ingestion_date_str / video_id
    normalized_stored_name = normalize_filename(src.name)
    destination_path = target_video_dir / normalized_stored_name
    metadata_path = target_video_dir / "metadata.json"

    # Collision-safe directory resolution: if target_video_dir exists for this date,
    # verify whether it belongs to the exact same content or a prefix collision.
    if target_video_dir.exists():
        if metadata_path.exists():
            try:
                existing_meta = load_ingestion_metadata(metadata_path)
                if existing_meta.content_sha256 and existing_meta.content_sha256 != content_hash:
                    # ID prefix collision on same date! Disambiguate directory with full hash suffix
                    target_video_dir = input_root_dir / ingestion_date_str / f"{video_id}_{content_hash[16:24]}"
                    destination_path = target_video_dir / normalized_stored_name
                    metadata_path = target_video_dir / "metadata.json"
            except Exception:
                pass

    target_video_dir.mkdir(parents=True, exist_ok=True)

    # 4. Atomic staging copy
    temp_dir = target_video_dir
    temp_prefix = f".staging_video_"
    temp_suffix = destination_path.suffix

    try:
        temp_fd, temp_file_path_str = tempfile.mkstemp(
            dir=temp_dir, prefix=temp_prefix, suffix=temp_suffix
        )
        os.close(temp_fd)
        temp_file_path = Path(temp_file_path_str)

        # Copy original without altering source
        shutil.copyfile(src, temp_file_path)
        shutil.copystat(src, temp_file_path)

        # Atomic promote: Avoid overwriting if another process staged the exact file concurrently
        try:
            # os.rename fails with FileExistsError on Windows if destination already exists
            os.rename(temp_file_path, destination_path)
        except FileExistsError:
            # Destination was created concurrently; remove temporary staging file
            temp_file_path.unlink(missing_ok=True)
            if compute_file_sha256(destination_path) == content_hash and metadata_path.exists():
                existing_meta = load_ingestion_metadata(metadata_path)
                return StagedInputResult(
                    is_staged=True,
                    source_path=src,
                    staged_path=destination_path,
                    metadata=existing_meta,
                    error_message=None,
                )
        except OSError:
            # Fallback for platforms where rename might replace
            if destination_path.exists():
                temp_file_path.unlink(missing_ok=True)
                if compute_file_sha256(destination_path) == content_hash and metadata_path.exists():
                    existing_meta = load_ingestion_metadata(metadata_path)
                    return StagedInputResult(
                        is_staged=True,
                        source_path=src,
                        staged_path=destination_path,
                        metadata=existing_meta,
                        error_message=None,
                    )
            else:
                temp_file_path.replace(destination_path)

        logger.info(f"Staged source video '{src.name}' -> '{destination_path}'")

    except Exception as exc:
        logger.error(f"Failed to stage video '{src}': {exc}", exc_info=True)
        if "temp_file_path" in locals() and temp_file_path.exists():
            temp_file_path.unlink(missing_ok=True)
        return StagedInputResult(
            is_staged=False,
            source_path=src,
            staged_path=None,
            metadata=None,
            error_message=f"Atomic file copy failed: {exc}",
        )

    # 5. Build and save ingestion metadata
    metadata = IngestionMetadata(
        schema_version="v1.0",
        video_id=video_id,
        original_filename=src.name,
        stored_filename=destination_path.name,
        ingested_at=ingested_at_iso,
        ingestion_date=ingestion_date_str,
        file_size_bytes=destination_path.stat().st_size,
        media_type=destination_path.suffix.lower().lstrip("."),
        content_sha256=content_hash,
        source_path=str(destination_path),
        probe_status="probed",
        media_info={
            "format_name": probe_res.format_name,
            "duration_seconds": probe_res.duration_seconds,
            "size_bytes": probe_res.size_bytes,
            "video_streams": [s.model_dump() for s in probe_res.video_streams],
            "audio_streams": [s.model_dump() for s in probe_res.audio_streams],
        },
    )

    save_ingestion_metadata(metadata_path, metadata)

    return StagedInputResult(
        is_staged=True,
        source_path=src,
        staged_path=destination_path,
        metadata=metadata,
        error_message=None,
    )
