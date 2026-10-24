"""Unit tests for subtitle cue generation, time formatting, and ASS/SRT script generation."""

import pytest
from app.domain.rendering.models import CaptionConfig
from app.domain.transcript.models import TranscriptSegment, WordTiming
from app.services.media.subtitles import (
    build_clip_cues,
    format_ass_time,
    format_srt_time,
    generate_ass_subtitle_content,
    generate_srt_subtitle_content,
)


def test_time_formatting_ass_and_srt():
    # 0 seconds
    assert format_ass_time(0.0) == "0:00:00.00"
    assert format_srt_time(0.0) == "00:00:00,000"

    # 65.432 seconds
    assert format_ass_time(65.432) == "0:01:05.43"
    assert format_srt_time(65.432) == "00:01:05,432"

    # Over 1 hour (3661.05s)
    assert format_ass_time(3661.05) == "1:01:01.05"
    assert format_srt_time(3661.05) == "01:01:01,050"


def test_build_clip_cues_with_word_timings():
    segments = [
        TranscriptSegment(
            id=0,
            start_seconds=10.0,
            end_seconds=20.0,
            duration_seconds=10.0,
            text="Hello world today we are testing",
            words=[
                WordTiming(word="Hello", start_seconds=10.0, end_seconds=11.0),
                WordTiming(word="world", start_seconds=11.0, end_seconds=12.0),
                WordTiming(word="today", start_seconds=12.0, end_seconds=13.0),
                WordTiming(word="we", start_seconds=13.0, end_seconds=14.0),
                WordTiming(word="are", start_seconds=14.0, end_seconds=15.0),
                WordTiming(word="testing", start_seconds=15.0, end_seconds=16.0),
            ],
        )
    ]

    # Candidate interval: [10.0, 25.0] (duration=15.0s)
    cues = build_clip_cues(
        candidate_start_seconds=10.0,
        candidate_end_seconds=25.0,
        transcript_segments=segments,
        max_words_per_cue=3,
    )

    # 6 words grouped by 3 -> 2 cues
    assert len(cues) == 2
    # Cue 1: [0.0 - 3.0s clip relative] "Hello world today"
    assert cues[0].start_seconds == 0.0
    assert cues[0].end_seconds == 3.0
    assert cues[0].text == "Hello world today"

    # Cue 2: [3.0 - 6.0s clip relative] "we are testing"
    assert cues[1].start_seconds == 3.0
    assert cues[1].end_seconds == 6.0
    assert cues[1].text == "we are testing"


def test_generate_ass_and_srt_scripts():
    segments = [
        TranscriptSegment(
            id=0,
            start_seconds=50.0,
            end_seconds=65.0,
            duration_seconds=15.0,
            text="Clip relative subtitle rendering test.",
        )
    ]
    cues = build_clip_cues(
        candidate_start_seconds=50.0,
        candidate_end_seconds=70.0,
        transcript_segments=segments,
    )
    assert len(cues) == 1
    cue = cues[0]
    assert cue.start_seconds == 0.0
    assert cue.end_seconds == 15.0

    ass_text = generate_ass_subtitle_content(cues, CaptionConfig())
    assert "[Script Info]" in ass_text
    assert "PlayResX: 1080" in ass_text
    assert "PlayResY: 1920" in ass_text
    assert "Dialogue: 0,0:00:00.00,0:00:15.00,Default,,0,0,0,,Clip relative subtitle rendering test." in ass_text

    srt_text = generate_srt_subtitle_content(cues)
    assert "00:00:00,000 --> 00:00:15,000" in srt_text
    assert "Clip relative subtitle rendering test." in srt_text
