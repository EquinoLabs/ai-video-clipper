"""Input staging and date-scoped materialization service.

Safely materializes original videos from init_input/ (the authoritative source library)
into the managed date-scoped input/ YYYY-MM-DD/<source_video_uuid>/ hierarchy with
collision-safe filenames, canonical UUID identities, and ingestion metadata tracking.
"""

import datetime
import logging
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import List, NamedTuple, Optional, Set, Tuple, Union

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


def get_local_date() -> datetime.date:
    """Get the current machine local date."""
    return datetime.datetime.now().astimezone().date()


def is_supported_video_file(path: Path) -> bool:
    """Check if file has a supported video extension and is a regular file."""
    p = Path(path)
    return p.is_file() and p.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS


def discover_video_files_in_folder(folder_path: Path) -> List[Path]:
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


def resolve_source_videos(
    init_input_dir: Path,
    mode: str,
    single: Optional[Union[str, Path]] = None,
    selected: Optional[List[Union[str, Path]]] = None,
) -> List[Path]:
    """Resolve source video paths from the authoritative init_input directory.
    
    Exactly one mode must be specified:
    - 'single': selects one specified video from init_input_dir
    - 'selected': selects a list of specified videos from init_input_dir
    - 'all': selects all eligible video files present in init_input_dir
    
    Args:
        init_input_dir: Path to the authoritative init_input/ directory.
        mode: Mode string ('single', 'selected', or 'all').
        single: Video filename or path (for 'single' mode).
        selected: List of video filenames or paths (for 'selected' mode).
        
    Returns:
        Deterministic list of resolved source video Path objects.
        
    Raises:
        ValueError: For invalid or ambiguous modes, or unsupported video formats.
        FileNotFoundError: If init_input_dir or any specified source file does not exist.
    """
    init_dir = Path(init_input_dir).resolve()
    if not init_dir.exists():
        if mode == "single" and single and Path(single).resolve().is_file():
            pass
        elif mode == "selected" and selected and all(Path(s).resolve().is_file() for s in selected):
            pass
        else:
            raise FileNotFoundError(f"Authoritative source library directory not found: '{init_dir}'")
    elif not init_dir.is_dir():
        raise ValueError(f"Authoritative source library path is not a directory: '{init_dir}'")

    if mode not in ("single", "selected", "all"):
        raise ValueError(f"Invalid selection mode: '{mode}'. Must be one of 'single', 'selected', 'all'.")

    def _resolve_one(spec: Union[str, Path]) -> Path:
        raw_p = Path(spec)
        # 1. If path points directly to an existing file
        if raw_p.resolve().is_file():
            target = raw_p.resolve()
        # 2. Check relative to init_dir
        elif init_dir.exists() and (init_dir / raw_p).resolve().is_file():
            target = (init_dir / raw_p).resolve()
        # 3. Check by filename inside init_dir
        elif init_dir.exists() and (init_dir / raw_p.name).is_file():
            target = (init_dir / raw_p.name).resolve()
        else:
            raise FileNotFoundError(f"Source video '{spec}' not found in source library '{init_dir}'.")

        if not is_supported_video_file(target):
            raise ValueError(
                f"File '{target.name}' is not a supported video file (supported: {', '.join(sorted(SUPPORTED_VIDEO_EXTENSIONS))})."
            )
        if target.stat().st_size == 0:
            raise ValueError(f"Source video '{target.name}' is empty (0 bytes).")
        return target

    if mode == "single":
        if not single:
            raise ValueError("Single video selection mode requires a video specification via --single.")
        return [_resolve_one(single)]

    elif mode == "selected":
        if not selected or len(selected) == 0:
            raise ValueError("Selected video mode requires one or more video specifications via --selected.")
        results = []
        for s in selected:
            results.append(_resolve_one(s))
        return results

    elif mode == "all":
        discovered = discover_video_files_in_folder(init_dir)
        valid_files = [f for f in discovered if is_supported_video_file(f) and f.stat().st_size > 0]
        return valid_files


def find_date_scoped_intake_record(
    input_root_dir: Path,
    date_str: str,
    source_uuid: str,
    content_hash: str,
) -> Optional[Tuple[Path, IngestionMetadata]]:
    """Check if a valid, consistent intake copy already exists for date_str and source_uuid.
    
    Validates:
    - Target directory exists: input/<date_str>/<source_uuid>/
    - metadata.json exists and is valid JSON matching IngestionMetadata schema
    - Metadata source_video_id or video_id matches expected source_uuid
    - Metadata content_sha256 matches expected content_hash
    - Staged media file exists, is non-empty, and matches metadata file_size_bytes
    - Staged media file content hash matches content_hash
    
    Returns:
        (staged_video_path, IngestionMetadata) if valid and consistent; otherwise None.
    """
    target_dir = input_root_dir / date_str / source_uuid
    if not target_dir.exists() or not target_dir.is_dir():
        return None

    meta_file = target_dir / "metadata.json"
    if not meta_file.is_file():
        return None

    try:
        meta = load_ingestion_metadata(meta_file)
    except Exception as exc:
        logger.warning("Corrupted or unreadable metadata at '%s': %s", meta_file, exc)
        return None

    # Validate source UUID
    recorded_uuid = meta.source_video_id or meta.video_id
    if recorded_uuid != source_uuid:
        logger.warning(
            "Metadata at '%s' has mismatched source UUID (expected=%s, actual=%s)",
            meta_file,
            source_uuid,
            recorded_uuid,
        )
        return None

    # Validate content hash
    target_hash = content_hash.strip().lower()
    recorded_hash = (meta.content_sha256 or "").strip().lower()
    if recorded_hash and recorded_hash != target_hash:
        logger.warning(
            "Metadata at '%s' has mismatched content hash (expected=%s, actual=%s)",
            meta_file,
            target_hash,
            recorded_hash,
        )
        return None

    # Locate candidate staged media file
    candidate_file: Optional[Path] = None
    if meta.stored_filename and (target_dir / meta.stored_filename).is_file():
        candidate_file = target_dir / meta.stored_filename
    else:
        for sibling in target_dir.iterdir():
            if is_supported_video_file(sibling):
                candidate_file = sibling
                break

    if not candidate_file or not candidate_file.is_file():
        logger.warning("Intake record at '%s' has missing media file.", target_dir)
        return None

    # Validate file size is non-empty and consistent
    try:
        file_size = candidate_file.stat().st_size
        if file_size == 0:
            logger.warning("Intake media file at '%s' is empty (0 bytes).", candidate_file)
            return None
        if meta.file_size_bytes > 0 and file_size != meta.file_size_bytes:
            logger.warning(
                "Intake media file at '%s' size mismatch (metadata=%d, disk=%d)",
                candidate_file,
                meta.file_size_bytes,
                file_size,
            )
            return None
    except Exception as exc:
        logger.warning("Could not stat intake media file '%s': %s", candidate_file, exc)
        return None

    # Verify on-disk SHA-256 hash
    try:
        actual_hash = compute_file_sha256(candidate_file)
        if actual_hash.lower() != target_hash:
            logger.warning(
                "Intake media file at '%s' hash mismatch (expected=%s, actual=%s)",
                candidate_file,
                target_hash,
                actual_hash,
            )
            return None
    except Exception as exc:
        logger.warning("Could not verify file hash for '%s': %s", candidate_file, exc)
        return None

    return candidate_file, meta


class StagedInputResult(NamedTuple):
    """Result of staging or materializing a source video file."""
    is_staged: bool
    source_path: Path
    staged_path: Optional[Path]
    metadata: Optional[IngestionMetadata]
    error_message: Optional[str] = None


def materialize_intake_video(
    source_file_path: Path,
    input_root: Path = Path("input"),
    target_date: Optional[Union[datetime.date, str]] = None,
) -> StagedInputResult:
    """Materialize an authoritative source video into the date-scoped input/ hierarchy.
    
    Structure:
        input/YYYY-MM-DD/<source_video_uuid>/<video_lower_snake_case.mp4>
        input/YYYY-MM-DD/<source_video_uuid>/metadata.json
        
    Rules:
        - Resolves canonical source UUID from content SHA-256 hash.
        - Materializes into the intake directory for target_date (defaults to current local date).
        - Reuses today's intake copy if valid and consistent without re-copying or modifying timestamp.
        - Detects and repairs incomplete or corrupted existing intake directories.
        - Never scans or selects from older date folders.
        - Handles concurrent materializations safely.
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

    # 2. Determine target date and canonical UUID
    if target_date is None:
        date_obj = get_local_date()
    elif isinstance(target_date, str):
        date_obj = datetime.date.fromisoformat(target_date)
    else:
        date_obj = target_date

    date_str = date_obj.strftime("%Y-%m-%d")
    content_hash = compute_file_sha256(src)
    source_uuid = generate_stable_video_id(content_hash)
    input_root_dir = Path(input_root).resolve()

    # 3. Check for existing valid intake copy for THIS specific date
    existing_record = find_date_scoped_intake_record(input_root_dir, date_str, source_uuid, content_hash)
    if existing_record:
        staged_path, existing_meta = existing_record
        logger.info(
            "Source video '%s' already materialized for date '%s' at '%s' (uuid=%s). Reusing.",
            src.name,
            date_str,
            staged_path,
            source_uuid,
        )
        return StagedInputResult(
            is_staged=True,
            source_path=src,
            staged_path=staged_path,
            metadata=existing_meta,
            error_message=None,
        )

    # 4. Probe source file to verify media streams before copying
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

    target_video_dir = input_root_dir / date_str / source_uuid
    normalized_stored_name = normalize_filename(src.name)
    destination_path = target_video_dir / normalized_stored_name
    metadata_path = target_video_dir / "metadata.json"

    # If target directory exists but was deemed incomplete/corrupt by find_date_scoped_intake_record, repair it
    if target_video_dir.exists():
        logger.warning(
            "Target intake directory '%s' exists but is incomplete or invalid. Repairing by re-materializing.",
            target_video_dir,
        )
        for item in target_video_dir.iterdir():
            if item.is_file():
                try:
                    item.unlink(missing_ok=True)
                except Exception:
                    pass

    target_video_dir.mkdir(parents=True, exist_ok=True)

    # 5. Atomic copy with temp file to avoid partial visibility
    unique_suffix = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
    temp_prefix = f".staging_video_{unique_suffix}_"
    temp_suffix = destination_path.suffix

    try:
        temp_fd, temp_file_path_str = tempfile.mkstemp(
            dir=target_video_dir, prefix=temp_prefix, suffix=temp_suffix
        )
        os.close(temp_fd)
        temp_file_path = Path(temp_file_path_str)

        shutil.copyfile(src, temp_file_path)
        shutil.copystat(src, temp_file_path)

        try:
            os.rename(temp_file_path, destination_path)
        except FileExistsError:
            temp_file_path.unlink(missing_ok=True)
            # Polling for concurrent writer to finish metadata
            for _ in range(25):
                if metadata_path.exists():
                    break
                time.sleep(0.02)
            existing = find_date_scoped_intake_record(input_root_dir, date_str, source_uuid, content_hash)
            if existing:
                return StagedInputResult(
                    is_staged=True,
                    source_path=src,
                    staged_path=existing[0],
                    metadata=existing[1],
                    error_message=None,
                )
        except OSError:
            if destination_path.exists():
                temp_file_path.unlink(missing_ok=True)
                for _ in range(25):
                    if metadata_path.exists():
                        break
                    time.sleep(0.02)
                existing = find_date_scoped_intake_record(input_root_dir, date_str, source_uuid, content_hash)
                if existing:
                    return StagedInputResult(
                        is_staged=True,
                        source_path=src,
                        staged_path=existing[0],
                        metadata=existing[1],
                        error_message=None,
                    )
            else:
                temp_file_path.replace(destination_path)

        logger.info(f"Materialized intake video '{src.name}' -> '{destination_path}'")

    except Exception as exc:
        logger.error(f"Failed to materialize video '{src}': {exc}", exc_info=True)
        if "temp_file_path" in locals() and temp_file_path.exists():
            temp_file_path.unlink(missing_ok=True)
        return StagedInputResult(
            is_staged=False,
            source_path=src,
            staged_path=None,
            metadata=None,
            error_message=f"Atomic file copy failed: {exc}",
        )

    # 6. Build and save ingestion metadata
    now_local = datetime.datetime.now().astimezone()
    ingested_at_iso = now_local.isoformat()

    metadata = IngestionMetadata(
        schema_version="v1.0",
        video_id=source_uuid,
        source_video_id=source_uuid,
        original_filename=src.name,
        stored_filename=destination_path.name,
        ingested_at=ingested_at_iso,
        ingestion_date=date_str,
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
    logger.info(f"Saved ingestion metadata: '{metadata_path}' (source_video_id={source_uuid})")

    return StagedInputResult(
        is_staged=True,
        source_path=src,
        staged_path=destination_path,
        metadata=metadata,
        error_message=None,
    )


def stage_input_video(
    source_file_path: Path,
    input_root: Path = Path("input"),
    target_date: Optional[Union[datetime.date, str]] = None,
) -> StagedInputResult:
    """Validate and atomically stage a source video into the date-scoped input/ directory.
    
    Provides backwards compatibility for callers of stage_input_video by routing through
    the shared materialize_intake_video implementation.
    """
    return materialize_intake_video(
        source_file_path=source_file_path,
        input_root=input_root,
        target_date=target_date,
    )
