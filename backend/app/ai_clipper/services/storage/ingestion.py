"""Source video ingestion service, filename normalization, and metadata persistence."""

import datetime
import hashlib
import logging
import os
import re
import shutil
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.ai_clipper.domain.ingestion.models import IngestionMetadata

logger = logging.getLogger(__name__)

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30), name="IST")


WINDOWS_RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
}


def normalize_filename(original_name: str, max_stem_length: int = 120) -> str:
    """Normalize incoming video filenames to safe lowercase snake_case.

    Rules:
    - Retains original file extension in lowercase.
    - Strips accents and converts unicode to closest ASCII characters.
    - Replaces spaces, hyphens, and non-alphanumeric punctuation with underscores.
    - Collapses consecutive underscores to single underscores.
    - Strips leading and trailing underscores from stem.
    - If stem becomes empty or matches a Windows reserved name, defaults to 'video'.
    - Safely truncates long stems to stay within Windows path-length limits.
    """
    cleaned = original_name.strip()
    if cleaned.startswith(".") and cleaned.count(".") == 1:
        stem = ""
        ext = cleaned
    else:
        stem, ext = os.path.splitext(cleaned)
    ext = ext.lower()

    # ASCII transliteration
    normalized_stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")
    normalized_stem = normalized_stem.lower()

    # Replace punctuation, spaces, dots, hyphens with underscores
    normalized_stem = re.sub(r"[^a-z0-9]+", "_", normalized_stem)
    normalized_stem = re.sub(r"_+", "_", normalized_stem).strip("_")

    if not normalized_stem or normalized_stem in WINDOWS_RESERVED_NAMES:
        normalized_stem = "video"
    elif len(normalized_stem) > max_stem_length:
        normalized_stem = normalized_stem[:max_stem_length].rstrip("_")
        if not normalized_stem:
            normalized_stem = "video"

    return f"{normalized_stem}{ext}"


def resolve_unique_input_path(date_dir: Path, normalized_name: str) -> Path:
    """Resolve a destination path under date_dir, suffixing deterministically on collision.

    Example:
    - 'video.mp4' -> 'video.mp4' if not existing
    - 'video.mp4' -> 'video_2.mp4' if 'video.mp4' exists
    - 'video_2.mp4' -> 'video_3.mp4' if 'video_2.mp4' exists
    """
    candidate = date_dir / normalized_name
    if not candidate.exists():
        return candidate

    stem, ext = os.path.splitext(normalized_name)
    counter = 2
    while True:
        candidate = date_dir / f"{stem}_{counter}{ext}"
        if not candidate.exists():
            return candidate
        counter += 1


def compute_file_sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file on disk."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def generate_stable_video_id(content_hash: str) -> str:
    """Generate a deterministic, date-independent video identity based on content SHA-256 hash.

    Format:
    vid_<hash[:16]> (e.g. vid_6cf414fcdae21d2e)
    """
    clean_hash = content_hash.strip().lower() if content_hash else "0" * 64
    return f"vid_{clean_hash[:16]}"


def generate_video_id(date_str: Optional[str] = None, content_hash: str = "") -> str:
    """Generate video identity.

    If date_str is provided, produces historical format f'vid_{date_token}_{hash_token}'
    for backwards compatibility. If date_str is omitted or None, produces stable
    date-independent video_id via generate_stable_video_id.
    """
    if date_str:
        date_token = date_str.replace("-", "")
        hash_token = content_hash[:8] if content_hash else "00000000"
        return f"vid_{date_token}_{hash_token}"
    return generate_stable_video_id(content_hash)


def save_ingestion_metadata(metadata_path: Path, metadata: IngestionMetadata) -> Path:
    """Save ingestion metadata atomically to disk with unique temp file per process/thread."""
    unique_suffix = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
    temp_path = metadata_path.with_name(f".{metadata_path.name}.{unique_suffix}.tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(metadata.model_dump_json(indent=2))
        try:
            # os.rename fails with FileExistsError on Windows if metadata_path already exists
            os.rename(temp_path, metadata_path)
        except FileExistsError:
            # Metadata was already created concurrently by another process
            temp_path.unlink(missing_ok=True)
        except OSError:
            if metadata_path.exists():
                temp_path.unlink(missing_ok=True)
            else:
                os.replace(temp_path, metadata_path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass
    return metadata_path


def load_ingestion_metadata(metadata_path: Path) -> IngestionMetadata:
    """Load and validate ingestion metadata from disk."""
    with open(metadata_path, "r", encoding="utf-8") as f:
        return IngestionMetadata.model_validate_json(f.read())


def ingest_source_video(
    source_path: Path,
    input_root: Path = Path("input"),
    date: Optional[datetime.date] = None,
    copy_file: bool = True,
) -> Tuple[Path, IngestionMetadata]:
    """Ingest a source video into the managed input directory hierarchy.

    Args:
        source_path: Path to the input video file.
        input_root: Base input directory (defaults to 'input').
        date: Ingestion date (defaults to current date in IST).
        copy_file: Whether to copy the file into input_root. If False, references existing file.

    Returns:
        Tuple of (destination_path, IngestionMetadata).
    """
    source_path = Path(source_path)
    if not source_path.exists():
        raise FileNotFoundError(f"Source file does not exist: {source_path}")

    now_ist = datetime.datetime.now(IST)
    if date is not None:
        date_str = date.strftime("%Y-%m-%d")
        ingested_at = datetime.datetime.combine(date, now_ist.time(), tzinfo=IST).isoformat()
    else:
        date_str = now_ist.strftime("%Y-%m-%d")
        ingested_at = now_ist.isoformat()

    date_dir = input_root / date_str
    date_dir.mkdir(parents=True, exist_ok=True)

    normalized_name = normalize_filename(source_path.name)
    destination_path = resolve_unique_input_path(date_dir, normalized_name)

    if copy_file:
        shutil.copy2(source_path, destination_path)
        inspect_target = destination_path
    else:
        inspect_target = source_path

    file_size_bytes = inspect_target.stat().st_size
    content_hash = compute_file_sha256(inspect_target)
    video_id = generate_video_id(date_str, content_hash)

    # Optional media probing
    media_info: Optional[Dict[str, Any]] = None
    probe_status = "skipped"
    try:
        from app.common.media.probing import probe_media_file
        probe_res = probe_media_file(inspect_target)
        probe_status = "probed"
        media_info = {
            "format_name": probe_res.format_name,
            "duration_seconds": probe_res.duration_seconds,
            "size_bytes": probe_res.size_bytes,
            "video_streams": [s.model_dump() for s in probe_res.video_streams],
            "audio_streams": [s.model_dump() for s in probe_res.audio_streams],
        }
    except Exception as exc:
        logger.debug("Media probing skipped or failed during ingestion for %s: %s", inspect_target, exc)
        probe_status = "failed"

    # Normalize relative source path with forward slashes
    try:
        rel_path = destination_path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        rel_path = destination_path.as_posix()

    metadata = IngestionMetadata(
        schema_version="v1.0",
        video_id=video_id,
        original_filename=source_path.name,
        stored_filename=destination_path.name,
        ingested_at=ingested_at,
        ingestion_date=date_str,
        file_size_bytes=file_size_bytes,
        media_type=destination_path.suffix.lower().lstrip("."),
        content_sha256=content_hash,
        source_path=rel_path,
        probe_status=probe_status,
        media_info=media_info,
    )

    metadata_path = destination_path.with_name(f"{destination_path.stem}__metadata.json")
    save_ingestion_metadata(metadata_path, metadata)

    return destination_path, metadata
