"""Output manager service for collision-safe run directories and atomic writes."""

import datetime
import json
import logging
import os
import re
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, Optional, Union
from pydantic import BaseModel

from app.domain.manifest.models import ClipMetadata, RunManifest

logger = logging.getLogger(__name__)

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30), name="IST")


def get_repository_root() -> Path:
    """Locate the git repository root or project root directory independent of working directory."""
    curr = Path(__file__).resolve()
    for parent in curr.parents:
        if (parent / ".git").exists() or (parent / "backend" / "app").exists():
            return parent
    return curr.parents[4]


DEFAULT_OUTPUT_ROOT: Path = (get_repository_root() / "outputs").resolve()

# Regex pattern for historical run directory format: HH_MM_SS__run_NNN
_HISTORICAL_RUN_PATTERN = re.compile(r"^\d{2}_\d{2}_\d{2}__run_(\d+)$")
# Regex pattern for new run directory format: run_NNN_HHMMSS (also matches run_NNN)
_NEW_RUN_PATTERN = re.compile(r"^run_(\d+)(?:_\d{6})?$")


class OutputManager:
    """Manages output directory hierarchies, atomic file creation, and manifest persistence."""

    def __init__(self, output_root: Optional[Union[str, Path]] = None) -> None:
        if output_root is None or output_root in ("outputs", Path("outputs")):
            self.output_root = DEFAULT_OUTPUT_ROOT
        else:
            self.output_root = Path(output_root).resolve()

    @staticmethod
    def get_ist_now() -> datetime.datetime:
        """Return current datetime in Asia/Kolkata (IST) timezone."""
        return datetime.datetime.now(IST)

    @staticmethod
    def _get_next_sequence_number(video_dir: Path) -> int:
        """Determine next sequential run number from existing runs in video_dir.

        Counts both historical runs (HH_MM_SS__run_NNN) and new runs (run_NNN_HHMMSS),
        as well as any directory representing a run (e.g. containing manifest.json).
        Calculates next_seq = max(run_count + 1, max_seq + 1) to ensure uniqueness
        even if past runs shared sequence numbers or skipped numbers.
        """
        if not video_dir.exists():
            return 1

        run_count = 0
        max_seq = 0

        for child in video_dir.iterdir():
            if not child.is_dir():
                continue

            matched = False
            m_new = _NEW_RUN_PATTERN.match(child.name)
            if m_new:
                matched = True
                seq_num = int(m_new.group(1))
                max_seq = max(max_seq, seq_num)
            else:
                m_hist = _HISTORICAL_RUN_PATTERN.match(child.name)
                if m_hist:
                    matched = True
                    seq_num = int(m_hist.group(1))
                    max_seq = max(max_seq, seq_num)

            if matched:
                run_count += 1
            else:
                # If directory contains run artifacts (manifest, transcript, candidates),
                # count it as an existing run attempt so failed or custom runs are accounted for.
                if (
                    (child / "manifest.json").exists()
                    or (child / "transcript.json").exists()
                    or (child / "candidates.json").exists()
                ):
                    run_count += 1

        return max(run_count + 1, max_seq + 1)

    def get_run_directory(
        self,
        video_identifier: str,
        run_time: Optional[datetime.datetime] = None,
    ) -> Path:
        """Determine a collision-safe run directory path without creating it.

        Layout:
        outputs/YYYY-MM-DD/<source_video_uuid>/run_NNN_HHMMSS/
        """
        now = run_time or self.get_ist_now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H%M%S")

        video_dir = self.output_root / date_str / video_identifier
        seq = self._get_next_sequence_number(video_dir)

        while True:
            run_candidate = video_dir / f"run_{seq:03d}_{time_str}"
            if not run_candidate.exists():
                return run_candidate
            seq += 1

    def create_run_directory(
        self,
        video_identifier: str,
        run_time: Optional[datetime.datetime] = None,
    ) -> Path:
        """Determine and create a collision-safe run directory.

        Creates directory safely handling concurrent processes or existing directories.
        """
        now = run_time or self.get_ist_now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H%M%S")

        video_dir = self.output_root / date_str / video_identifier
        video_dir.mkdir(parents=True, exist_ok=True)
        seq = self._get_next_sequence_number(video_dir)

        while True:
            candidate_dir = video_dir / f"run_{seq:03d}_{time_str}"
            try:
                candidate_dir.mkdir(parents=True, exist_ok=False)
                return candidate_dir
            except FileExistsError:
                seq += 1

    @staticmethod
    def get_long_clip_dir(run_dir: Path, clip_identity: Union[str, uuid.UUID, int]) -> Path:
        """Get standard folder path for a long clip (long_clips/<clip_uuid>)."""
        if isinstance(clip_identity, int):
            return run_dir / "long_clips" / f"clip_{clip_identity:02d}"
        return run_dir / "long_clips" / str(clip_identity)

    @staticmethod
    def get_short_clip_dir(run_dir: Path, clip_identity: Union[str, uuid.UUID, int]) -> Path:
        """Get standard folder path for a short clip (short_clips/<clip_uuid>)."""
        if isinstance(clip_identity, int):
            return run_dir / "short_clips" / f"clip_{clip_identity:02d}"
        return run_dir / "short_clips" / str(clip_identity)

    @staticmethod
    def write_text_atomic(target_path: Path, content: str) -> Path:
        """Write string content atomically to target_path via a temporary file."""
        target_path = Path(target_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        temp_suffix = f".{target_path.name}.tmp.{uuid.uuid4().hex[:8]}"
        temp_file = target_path.with_name(temp_suffix)

        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_file, target_path)
            return target_path
        finally:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass

    def write_json_atomic(
        self,
        target_path: Path,
        data: Union[BaseModel, Dict[str, Any]],
        indent: int = 2,
    ) -> Path:
        """Serialize and atomically write a Pydantic model or dict to target_path."""
        if isinstance(data, BaseModel):
            content = data.model_dump_json(indent=indent)
        else:
            content = json.dumps(data, indent=indent)
        return self.write_text_atomic(target_path, content)

    @staticmethod
    def read_json(target_path: Path) -> Dict[str, Any]:
        """Read and parse JSON file from disk."""
        with open(target_path, "r", encoding="utf-8") as f:
            return json.load(f)

    @contextmanager
    def stage_media_path(self, target_path: Path) -> Generator[Path, None, None]:
        """Context manager providing an atomic staging path (.rendering.mp4).

        On successful context exit, atomically promotes the staged file to target_path.
        On exception, cleans up the staging file safely so failed renders are never published.
        """
        target_path = Path(target_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        staging_name = f"{target_path.stem}.rendering{target_path.suffix}"
        staging_path = target_path.with_name(staging_name)

        if staging_path.exists():
            staging_path.unlink()

        try:
            yield staging_path
            if staging_path.exists():
                os.replace(staging_path, target_path)
        except Exception:
            if staging_path.exists():
                try:
                    staging_path.unlink()
                except OSError:
                    pass
            raise

    def save_manifest(self, run_dir: Path, manifest: RunManifest) -> Path:
        """Atomically persist RunManifest to run_dir/manifest.json."""
        manifest_path = Path(run_dir) / "manifest.json"
        return self.write_json_atomic(manifest_path, manifest)

    def load_manifest(self, run_dir: Path) -> RunManifest:
        """Load and validate RunManifest from run_dir/manifest.json."""
        manifest_path = Path(run_dir) / "manifest.json"
        with open(manifest_path, "r", encoding="utf-8") as f:
            return RunManifest.model_validate_json(f.read())

    def save_clip_metadata(self, clip_dir: Path, metadata: ClipMetadata) -> Path:
        """Atomically persist ClipMetadata to clip_dir/metadata.json."""
        metadata_path = Path(clip_dir) / "metadata.json"
        return self.write_json_atomic(metadata_path, metadata)

    def load_clip_metadata(self, clip_dir: Path) -> ClipMetadata:
        """Load and validate ClipMetadata from clip_dir/metadata.json."""
        metadata_path = Path(clip_dir) / "metadata.json"
        with open(metadata_path, "r", encoding="utf-8") as f:
            return ClipMetadata.model_validate_json(f.read())
