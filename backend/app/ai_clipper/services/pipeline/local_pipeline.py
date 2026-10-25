"""Local media and transcription pipeline coordinator."""

import json
import logging
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.core.config import get_settings
from app.ai_clipper.domain.transcript.models import (
    SourceMediaMetadata,
    TranscriptArtifact,
    TranscriptionRunMetadata,
)
from app.ai_clipper.services.media.extraction import extract_audio_to_wav
from app.common.media.probing import probe_media_file
from app.ai_clipper.services.transcription.base import TranscriptionProvider
from app.ai_clipper.services.transcription.faster_whisper_adapter import FasterWhisperAdapter

logger = logging.getLogger(__name__)


class PipelineExecutionError(Exception):
    """Raised when the local pipeline fails during execution."""
    pass


class LocalPipelineResult:
    """Result data container for a completed local pipeline execution."""

    def __init__(
        self,
        source_path: Path,
        output_dir: Path,
        transcript_artifact_path: Path,
        extracted_audio_path: Optional[Path],
        artifact: TranscriptArtifact,
        elapsed_seconds: float,
    ):
        self.source_path = source_path
        self.output_dir = output_dir
        self.transcript_artifact_path = transcript_artifact_path
        self.extracted_audio_path = extracted_audio_path
        self.artifact = artifact
        self.elapsed_seconds = elapsed_seconds


def run_local_pipeline(
    source_file_path: Path,
    output_dir: Optional[Path] = None,
    transcription_provider: Optional[TranscriptionProvider] = None,
    model_name: Optional[str] = None,
    word_timestamps: bool = True,
    language: Optional[str] = None,
    keep_audio: bool = False,
) -> LocalPipelineResult:
    """Execute the Phase 1 local media and transcription pipeline:
    1. Validate source path and accessibility.
    2. Probe media with ffprobe (metadata, streams, duration).
    3. Extract audio to 16 kHz mono PCM WAV using FFmpeg.
    4. Run local transcription (Whisper adapter).
    5. Construct normalized TranscriptArtifact.
    6. Write transcript.json atomically to the output directory.
    7. Clean up temporary audio unless keep_audio is True.
    """
    start_time = time.time()
    source_path = Path(source_file_path).resolve()

    if not source_path.exists():
        raise PipelineExecutionError(f"Input file not found: {source_path}")
    if not source_path.is_file():
        raise PipelineExecutionError(f"Input path is not a regular file: {source_path}")

    # Generate isolated output directory if not provided
    if output_dir is None:
        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe_stem = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in source_path.stem)
        target_out_dir = Path("outputs") / f"{safe_stem}_{timestamp_str}"
    else:
        target_out_dir = Path(output_dir).resolve()

    target_out_dir.mkdir(parents=True, exist_ok=True)

    temp_audio_path = target_out_dir / "extracted_audio_16k.wav"
    artifact_final_path = target_out_dir / "transcript.json"

    try:
        # Step 1: Media Probing
        logger.info(f"[1/4] Probing source media: {source_path.name}")
        probe_res = probe_media_file(source_path)
        logger.info(
            f"      Format: {probe_res.format_name}, Duration: {probe_res.duration_seconds:.2f}s, "
            f"Video streams: {len(probe_res.video_streams)}, Audio streams: {len(probe_res.audio_streams)}"
        )

        selected_audio = probe_res.audio_streams[probe_res.selected_audio_stream_index]

        # Step 2: Audio Extraction
        logger.info(f"[2/4] Extracting audio stream {selected_audio.index} to 16kHz mono WAV...")
        extraction_res = extract_audio_to_wav(
            input_video_path=source_path,
            output_wav_path=temp_audio_path,
            stream_index=probe_res.selected_audio_stream_id,
        )
        logger.info(f"      Extracted audio size: {extraction_res.size_bytes / (1024 * 1024):.2f} MB")

        # Step 3: Local Transcription
        logger.info(f"[3/4] Transcribing audio with local Whisper adapter...")
        provider = transcription_provider or FasterWhisperAdapter(model_size_or_path=model_name)
        # Pass probed duration only when strictly positive
        max_dur = probe_res.duration_seconds if probe_res.duration_seconds > 0.0 else None
        trans_res = provider.transcribe(
            audio_file_path=extraction_res.output_path,
            word_timestamps=word_timestamps,
            language=language,
            max_duration_seconds=max_dur,
        )
        logger.info(
            f"      Transcription complete: {len(trans_res.segments)} segments, "
            f"detected language: {trans_res.language} ({trans_res.language_probability})"
        )

        # Step 4: Construct and Write Transcript Artifact
        logger.info(f"[4/4] Writing normalized transcript artifact...")
        total_words = 0
        for seg in trans_res.segments:
            if seg.words:
                total_words += len(seg.words)
            else:
                total_words += len(seg.text.split())

        artifact = TranscriptArtifact(
            schema_version="v1.0",
            source_media=SourceMediaMetadata(
                filename=source_path.name,
                format_name=probe_res.format_name,
                duration_seconds=probe_res.duration_seconds,
                size_bytes=probe_res.size_bytes,
                video_streams_count=len(probe_res.video_streams),
                audio_streams_count=len(probe_res.audio_streams),
                selected_audio_stream_index=probe_res.selected_audio_stream_index,
                audio_codec=selected_audio.codec_name,
                audio_sample_rate=selected_audio.sample_rate,
                audio_channels=selected_audio.channels,
            ),
            transcription=TranscriptionRunMetadata(
                provider=trans_res.provider,
                model=trans_res.model,
                language=trans_res.language,
                language_probability=trans_res.language_probability,
                word_timestamps_enabled=word_timestamps,
                parameters={
                    "vad_filter": True,
                    "target_audio_sample_rate": 16000,
                    "target_audio_channels": 1,
                },
                duration_processed_seconds=trans_res.duration_seconds or probe_res.duration_seconds,
            ),
            word_timestamps_available=trans_res.word_timestamps_available,
            segment_count=len(trans_res.segments),
            total_words_count=total_words,
            warnings=trans_res.warnings,
            segments=trans_res.segments,
        )

        # Atomic file write: write to temp file in destination directory, then replace
        temp_artifact_fd, temp_artifact_path_str = tempfile.mkstemp(
            dir=target_out_dir, prefix="transcript_", suffix=".tmp"
        )
        with os.fdopen(temp_artifact_fd, "w", encoding="utf-8") as f:
            f.write(artifact.model_dump_json(indent=2))

        Path(temp_artifact_path_str).replace(artifact_final_path)
        logger.info(f"      Transcript artifact saved: {artifact_final_path}")

        # Clean up temporary audio if not requested
        if not keep_audio and temp_audio_path.exists():
            temp_audio_path.unlink(missing_ok=True)
            saved_audio_path = None
        else:
            saved_audio_path = temp_audio_path

        elapsed = time.time() - start_time
        logger.info(f"Pipeline completed successfully in {elapsed:.2f}s.")

        return LocalPipelineResult(
            source_path=source_path,
            output_dir=target_out_dir,
            transcript_artifact_path=artifact_final_path,
            extracted_audio_path=saved_audio_path,
            artifact=artifact,
            elapsed_seconds=elapsed,
        )

    except Exception as exc:
        # Clean up incomplete files on error
        if temp_audio_path.exists() and not keep_audio:
            temp_audio_path.unlink(missing_ok=True)
        logger.error(f"Pipeline execution failed: {exc}", exc_info=True)
        raise PipelineExecutionError(f"Pipeline failed: {exc}") from exc
