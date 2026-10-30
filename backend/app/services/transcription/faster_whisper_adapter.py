"""Local transcription adapter using faster-whisper."""

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import get_settings
from app.domain.transcript.models import TranscriptSegment, WordTiming
from app.services.transcription.base import (
    TranscriptionProvider,
    TranscriptionProviderError,
    TranscriptionResult,
)

logger = logging.getLogger(__name__)


class FasterWhisperAdapter(TranscriptionProvider):
    """Adapter for local speech-to-text using faster-whisper (CTranslate2 backend).

    Features:
    - High-throughput execution with quantized models (e.g. int8 or float16).
    - True word-level timestamps when word_timestamps=True.
    - Preserves segment-level timestamps when word timestamps are unavailable.
    - Normalizes into stable TranscriptSegment domain models.
    """

    def __init__(
        self,
        model_size_or_path: Optional[str] = None,
        device: str = "cpu",
        compute_type: str = "int8",
        cpu_threads: int = 4,
    ):
        settings = get_settings()
        self.model_name = model_size_or_path or settings.whisper_model
        self.device = device
        self.compute_type = compute_type
        self.cpu_threads = cpu_threads
        self._model = None

    def _get_model(self):
        """Lazy load model to avoid memory overhead during non-transcription operations."""
        if self._model is None:
            try:
                import av
                # PyAV >=19 removed 'metadata_errors' keyword argument which faster-whisper passes.
                # Wrap av.open to maintain forward compatibility.
                if hasattr(av, "open") and not getattr(av.open, "_is_compat_patched", False):
                    _orig_av_open = av.open

                    def _compat_av_open(*args, **kwargs):
                        kwargs.pop("metadata_errors", None)
                        return _orig_av_open(*args, **kwargs)

                    _compat_av_open._is_compat_patched = True
                    av.open = _compat_av_open

                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise TranscriptionProviderError(
                    "The 'faster-whisper' package is not installed. "
                    "Install it via: pip install faster-whisper"
                ) from exc

            logger.info(
                f"Loading faster-whisper model '{self.model_name}' "
                f"on {self.device} (compute_type={self.compute_type})..."
            )
            start_time = time.time()
            try:
                self._model = WhisperModel(
                    self.model_name,
                    device=self.device,
                    compute_type=self.compute_type,
                    cpu_threads=self.cpu_threads,
                )
            except Exception as exc:
                raise TranscriptionProviderError(
                    f"Failed to load Whisper model '{self.model_name}': {exc}"
                ) from exc
            elapsed = time.time() - start_time
            logger.info(f"Model '{self.model_name}' loaded in {elapsed:.2f}s")
        return self._model

    def transcribe(
        self,
        audio_file_path: Path,
        word_timestamps: bool = True,
        language: Optional[str] = None,
        max_duration_seconds: Optional[float] = None,
    ) -> TranscriptionResult:
        """Transcribe audio file into normalized segments with absolute timestamps.

        Args:
            audio_file_path: Path to the 16kHz mono WAV audio file.
            word_timestamps: Whether to extract word-level timings.
            language: Optional language code hint (e.g. 'en').
            max_duration_seconds: Optional duration limit (seconds) derived from source media probing.
                When provided, clamps segment and word timestamps to prevent timeline overruns.

        Raises:
            ValueError: If max_duration_seconds is not positive or finite.
            TranscriptionProviderError: If the audio file is missing or model inference fails.
        """
        resolved_path = Path(audio_file_path).resolve()
        if not resolved_path.exists() or not resolved_path.is_file():
            raise TranscriptionProviderError(f"Audio file not found: {resolved_path}")

        # Validate max_duration_seconds if supplied
        limit_duration: Optional[float] = None
        if max_duration_seconds is not None:
            import math
            if (
                not isinstance(max_duration_seconds, (int, float))
                or math.isnan(max_duration_seconds)
                or math.isinf(max_duration_seconds)
                or max_duration_seconds <= 0.0
            ):
                raise ValueError(
                    f"max_duration_seconds must be a positive, finite number; got {max_duration_seconds!r}"
                )
            limit_duration = round(float(max_duration_seconds), 3)

        model = self._get_model()

        logger.info(
            f"Transcribing audio file: {resolved_path.name} "
            f"(word_timestamps={word_timestamps}, max_duration={limit_duration}s)..."
        )
        start_time = time.time()

        try:
            segments_gen, info = model.transcribe(
                str(resolved_path),
                word_timestamps=word_timestamps,
                language=language,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
            )
        except Exception as exc:
            raise TranscriptionProviderError(f"Transcription failed during model inference: {exc}") from exc

        segments: List[TranscriptSegment] = []
        has_words = False
        segment_id = 0

        prev_end = 0.0
        for seg in segments_gen:
            clean_text = seg.text.strip()
            if not clean_text:
                continue

            seg_start = max(0.0, round(float(seg.start), 3))
            seg_end = max(seg_start, round(float(seg.end), 3))

            # Clamp to max_duration_seconds if duration boundary is enforced
            if limit_duration is not None:
                if seg_start >= limit_duration:
                    logger.debug(
                        f"Skipping segment starting at or beyond max duration ({seg_start} >= {limit_duration})"
                    )
                    break
                seg_end = min(seg_end, limit_duration)
                seg_start = min(seg_start, seg_end)

            # Ensure chronological monotonicity for segments
            if seg_start < prev_end:
                logger.debug(f"Adjusting minor segment overlap: {seg_start} -> {prev_end}")
                seg_start = prev_end
                seg_end = max(seg_start, seg_end)
                if limit_duration is not None:
                    seg_end = min(seg_end, limit_duration)

            if seg_start >= seg_end:
                logger.debug(f"Skipping collapsed segment after duration/monotonicity clamping: [{seg_start}, {seg_end}]")
                continue

            prev_end = seg_end

            words_list: Optional[List[WordTiming]] = None
            if word_timestamps and hasattr(seg, "words") and seg.words:
                words_list = []
                for w in seg.words:
                    w_text = w.word.strip()
                    if not w_text:
                        continue

                    raw_w_start = round(float(w.start), 3)
                    raw_w_end = round(float(w.end), 3)

                    # Ensure start <= end from raw output if inverted
                    if raw_w_end < raw_w_start:
                        raw_w_start, raw_w_end = raw_w_end, raw_w_start

                    # If the entire word lies completely outside the parent segment bounds, skip it
                    if raw_w_end <= seg_start or raw_w_start >= seg_end:
                        logger.debug(
                            f"Dropping out-of-bounds word '{w_text}': "
                            f"raw=[{raw_w_start}, {raw_w_end}], seg=[{seg_start}, {seg_end}]"
                        )
                        continue

                    # Clamp word start and end strictly within parent segment [seg_start, seg_end]
                    w_start = max(seg_start, min(raw_w_start, seg_end))
                    w_end = min(seg_end, max(raw_w_end, w_start))

                    if w_start >= w_end:
                        logger.debug(
                            f"Dropping collapsed word '{w_text}': "
                            f"clamped=[{w_start}, {w_end}], seg=[{seg_start}, {seg_end}]"
                        )
                        continue

                    prob = (
                        round(float(w.probability), 3)
                        if hasattr(w, "probability") and w.probability is not None
                        else None
                    )
                    words_list.append(
                        WordTiming(
                            word=w_text,
                            start_seconds=w_start,
                            end_seconds=w_end,
                            probability=prob,
                        )
                    )
                if words_list:
                    has_words = True

            dur = round(seg_end - seg_start, 3)
            segments.append(
                TranscriptSegment(
                    id=segment_id,
                    start_seconds=seg_start,
                    end_seconds=seg_end,
                    duration_seconds=dur,
                    text=clean_text,
                    words=words_list if (words_list and len(words_list) > 0) else None,
                    speaker_label=None,  # Whisper does not perform diarization
                )
            )
            segment_id += 1

        elapsed = time.time() - start_time
        detected_lang = getattr(info, "language", None)
        lang_prob = round(float(info.language_probability), 3) if hasattr(info, "language_probability") and info.language_probability is not None else None
        audio_dur = round(float(getattr(info, "duration", 0.0)), 3)

        warnings = [
            "Local Whisper transcription does not provide speaker diarization. Speaker labels are unassigned."
        ]
        if word_timestamps and not has_words:
            warnings.append("Word-level timestamps were requested but not returned by the model for any segment.")

        logger.info(
            f"Transcription finished in {elapsed:.2f}s: {len(segments)} segments, "
            f"lang={detected_lang} ({lang_prob}), word_timestamps={has_words}"
        )

        return TranscriptionResult(
            segments=segments,
            language=detected_lang,
            language_probability=lang_prob,
            duration_seconds=audio_dur,
            word_timestamps_available=has_words,
            provider="faster-whisper",
            model=self.model_name,
            warnings=warnings,
        )
