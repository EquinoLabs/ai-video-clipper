"""Unit tests for Stage 2 long-clip discovery, boundary refinement, and clean master rendering."""

from pathlib import Path
import pytest

from app.api.v1.schemas.candidates import EditorialGoal, GenerationSettings
from app.domain.manifest.models import ClipMetadata, ManifestLongClipItem
from app.domain.rendering.models import FramingConfig, OutputConfig, RenderValidationResult
from app.domain.transcript.models import (
    SourceMediaMetadata,
    TranscriptArtifact,
    TranscriptionRunMetadata,
    TranscriptSegment,
    WordTiming,
)
from app.services.candidates.boundaries import (
    BoundaryRefinementConfig,
    refine_candidate_boundaries,
)
from app.services.llm.prompts import build_system_prompt, build_user_prompt
from app.services.rendering.long_clip_renderer import render_long_clip_package
from app.services.storage.output_manager import OutputManager
from app.services.transcription.slicing import slice_transcript_for_long_clip


@pytest.fixture
def sample_source_transcript() -> TranscriptArtifact:
    """Fixture providing a rich transcript with word-level timings."""
    segments = [
        TranscriptSegment(
            id=0,
            start_seconds=11.73,
            end_seconds=15.87,
            duration_seconds=4.14,
            text="Thank you for playing reverse charades with me.",
            words=[
                WordTiming(word="Thank", start_seconds=11.73, end_seconds=12.05),
                WordTiming(word="you", start_seconds=12.05, end_seconds=12.19),
                WordTiming(word="for", start_seconds=12.19, end_seconds=12.29),
                WordTiming(word="playing", start_seconds=12.29, end_seconds=12.75),
                WordTiming(word="reverse", start_seconds=12.75, end_seconds=13.20),
                WordTiming(word="charades", start_seconds=13.20, end_seconds=13.90),
                WordTiming(word="with", start_seconds=13.90, end_seconds=14.10),
                WordTiming(word="me.", start_seconds=14.10, end_seconds=14.50),
            ],
        ),
        TranscriptSegment(
            id=1,
            start_seconds=15.87,
            end_seconds=20.45,
            duration_seconds=4.58,
            text="I mean are you competitive when you play games?",
            words=[
                WordTiming(word="I", start_seconds=15.87, end_seconds=16.00),
                WordTiming(word="mean", start_seconds=16.00, end_seconds=16.20),
                WordTiming(word="are", start_seconds=16.20, end_seconds=16.40),
                WordTiming(word="you", start_seconds=16.40, end_seconds=16.60),
                WordTiming(word="competitive", start_seconds=16.60, end_seconds=17.50),
                WordTiming(word="when", start_seconds=17.50, end_seconds=17.80),
                WordTiming(word="you", start_seconds=17.80, end_seconds=18.00),
                WordTiming(word="play", start_seconds=18.00, end_seconds=18.30),
                WordTiming(word="games?", start_seconds=18.30, end_seconds=18.80),
            ],
        ),
        TranscriptSegment(
            id=2,
            start_seconds=55.56,
            end_seconds=59.42,
            duration_seconds=3.86,
            text="You know I really and I play for money too.",
            words=[
                WordTiming(word="You", start_seconds=55.56, end_seconds=55.80),
                WordTiming(word="know", start_seconds=55.80, end_seconds=56.00),
                WordTiming(word="I", start_seconds=56.00, end_seconds=56.20),
                WordTiming(word="really", start_seconds=56.20, end_seconds=56.90),
                WordTiming(word="and", start_seconds=56.90, end_seconds=57.20),
                WordTiming(word="I", start_seconds=57.20, end_seconds=57.40),
                WordTiming(word="play", start_seconds=57.40, end_seconds=57.80),
                WordTiming(word="for", start_seconds=57.80, end_seconds=58.20),
                WordTiming(word="money", start_seconds=58.20, end_seconds=58.80),
                WordTiming(word="too.", start_seconds=58.80, end_seconds=59.42),
            ],
        ),
        TranscriptSegment(
            id=3,
            start_seconds=62.16,
            end_seconds=64.46,
            duration_seconds=2.30,
            text="Is there a party game you are especially good at?",
            words=[
                WordTiming(word="Is", start_seconds=62.16, end_seconds=62.40),
                WordTiming(word="there", start_seconds=62.40, end_seconds=62.60),
                WordTiming(word="a", start_seconds=62.60, end_seconds=62.70),
                WordTiming(word="party", start_seconds=62.70, end_seconds=63.00),
                WordTiming(word="game", start_seconds=63.00, end_seconds=63.30),
                WordTiming(word="you", start_seconds=63.30, end_seconds=63.50),
                WordTiming(word="are", start_seconds=63.50, end_seconds=63.70),
                WordTiming(word="especially", start_seconds=63.70, end_seconds=64.10),
                WordTiming(word="good", start_seconds=64.10, end_seconds=64.30),
                WordTiming(word="at?", start_seconds=64.30, end_seconds=64.46),
            ],
        ),
    ]

    return TranscriptArtifact(
        schema_version="v1.0",
        source_media=SourceMediaMetadata(
            filename="source.mp4",
            format_name="mov,mp4",
            duration_seconds=120.0,
            size_bytes=1000000,
            video_streams_count=1,
            audio_streams_count=1,
            selected_audio_stream_index=0,
            audio_codec="aac",
            audio_sample_rate=44100,
            audio_channels=2,
        ),
        transcription=TranscriptionRunMetadata(
            provider="faster-whisper",
            model="base",
            word_timestamps_enabled=True,
            duration_processed_seconds=120.0,
        ),
        word_timestamps_available=True,
        segment_count=len(segments),
        segments=segments,
    )


# -----------------------------------------------------------------------------
# 1. GenerationSettings & Long-Clip Duration Bounds
# -----------------------------------------------------------------------------
def test_generation_settings_for_long_and_short_clips():
    long_cfg = GenerationSettings.for_long_clips()
    assert long_cfg.min_duration_seconds == 30.0
    assert long_cfg.preferred_min_seconds == 45.0
    assert long_cfg.preferred_max_seconds == 120.0
    assert long_cfg.target_duration_seconds == 90.0
    assert long_cfg.max_duration_seconds == 180.0

    short_cfg = GenerationSettings.for_short_clips()
    assert short_cfg.min_duration_seconds == 10.0
    assert short_cfg.target_duration_seconds == 30.0
    assert short_cfg.max_duration_seconds == 60.0

    # Custom valid configuration within bounds
    custom = GenerationSettings.for_long_clips(
        min_duration_seconds=35.0,
        target_duration_seconds=80.0,
        max_duration_seconds=150.0,
    )
    assert custom.min_duration_seconds == 35.0
    assert custom.max_duration_seconds == 150.0


def test_long_clip_prompts_selection():
    settings = GenerationSettings.for_long_clips()
    prompt = build_system_prompt(goal=EditorialGoal.HUMOR, settings=settings, is_long_clip=True)
    assert "long-form conversational content curator" in prompt
    assert "30.0 <= (end_seconds - start_seconds) <= 180.0" in prompt
    assert "COMPLETE, STANDALONE CONVERSATIONAL ARCS" in prompt

    user_p = build_user_prompt("Transcript content", is_long_clip=True)
    assert "complete conversational moments and story arcs" in user_p
    assert "conversational closure (including room reactions/laughter)" in user_p


# -----------------------------------------------------------------------------
# 2. Boundary Refinement & Word-Timestamp Snapping
# -----------------------------------------------------------------------------
def test_boundary_refinement_prevents_mid_word_cuts(sample_source_transcript):
    # Slice that cuts directly through the word 'playing' (12.29s - 12.75s) at 12.50s
    res = refine_candidate_boundaries(
        start_seconds=12.50,
        end_seconds=18.00,
        segments=sample_source_transcript.segments,
        source_duration_seconds=120.0,
    )
    # The start should snap out to word start (12.29s) or into preceding silence
    assert res.refined_start_seconds <= 12.29
    assert res.word_integrity_maintained is True


def test_boundary_refinement_extends_into_post_dialogue_laughter(sample_source_transcript):
    # Moment A ends dialogue at 59.42s ("I play for money too").
    # The next segment doesn't start until 62.16s (2.74s of silence/laughter).
    res = refine_candidate_boundaries(
        start_seconds=11.73,
        end_seconds=59.42,
        segments=sample_source_transcript.segments,
        source_duration_seconds=120.0,
        config=BoundaryRefinementConfig(outward_cushion_seconds=1.5, max_extension_seconds=3.0),
    )
    # The end should safely extend into the laughter cushion (up to 59.42 + 1.5 = 60.92)
    # but never encroach on 62.16s
    assert res.refined_end_seconds > 59.42
    assert res.refined_end_seconds <= 62.11
    assert res.end_adjusted is True


def test_boundary_refinement_respects_hard_limits(sample_source_transcript):
    # Test that max_clip_duration_seconds (e.g. 60.0s) is strictly respected
    res = refine_candidate_boundaries(
        start_seconds=11.73,
        end_seconds=71.73,  # already 60s
        segments=sample_source_transcript.segments,
        source_duration_seconds=120.0,
        max_clip_duration_seconds=60.0,
        config=BoundaryRefinementConfig(outward_cushion_seconds=2.0),
    )
    assert res.refined_duration_seconds <= 60.001
    assert res.refined_end_seconds <= 120.0
    assert res.refined_start_seconds >= 0.0


# -----------------------------------------------------------------------------
# 3. Transcript Slicing for Long Clips
# -----------------------------------------------------------------------------
def test_slice_transcript_for_long_clip(sample_source_transcript):
    # Slice interval from 11.73s to 59.42s
    sliced = slice_transcript_for_long_clip(
        source_artifact=sample_source_transcript,
        clip_start_seconds=11.73,
        clip_end_seconds=59.42,
        clip_id="lng_001",
    )

    assert sliced.source_media.filename == "lng_001.mp4"
    assert round(sliced.source_media.duration_seconds, 2) == 47.69
    assert len(sliced.segments) == 3

    # Segment 0 local timing must start at 0.0s
    seg0 = sliced.segments[0]
    assert seg0.start_seconds == 0.0
    assert seg0.words[0].word == "Thank"
    assert seg0.words[0].start_seconds == 0.0

    # Last segment words should be inside local duration
    seg_last = sliced.segments[-1]
    assert seg_last.end_seconds <= 47.69
    assert seg_last.words[-1].word == "too."
    assert seg_last.words[-1].end_seconds <= 47.69


# -----------------------------------------------------------------------------
# 4. Long-Clip Clean Master Package Rendering & Manifest Integration
# -----------------------------------------------------------------------------
def test_render_long_clip_package_flow(tmp_path: Path, sample_source_transcript, monkeypatch):
    mgr = OutputManager(output_root=tmp_path / "outputs")
    run_dir = mgr.create_run_directory("anne_hathaway")
    source_video = tmp_path / "source.mp4"
    source_video.write_text("mock video content")

    # Mock render_candidate_clip so FFmpeg is not required in pure unit tests
    def mock_render(output_mp4_path, **kwargs):
        p = Path(output_mp4_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("rendered mp4 bytes")
        return RenderValidationResult(
            is_valid=True,
            output_path=p,
            file_size_bytes=100,
            duration_seconds=kwargs.get("candidate_end_seconds", 0) - kwargs.get("candidate_start_seconds", 0),
            width=1080,
            height=1920,
            video_codec="h264",
            audio_codec="aac",
            has_audio=True,
        )

    monkeypatch.setattr("app.services.rendering.long_clip_renderer.render_candidate_clip", mock_render)

    clip_meta, manifest_item = render_long_clip_package(
        source_video_path=source_video,
        source_transcript=sample_source_transcript,
        clip_id="lng_001",
        clip_index=1,
        source_start_seconds=11.73,
        source_end_seconds=63.00,
        run_dir=run_dir,
        source_video_id="vid_20261024_01",
        output_manager=mgr,
        render_final_deliverable=False,  # Clean master only
        hook="Jimmy competing against his kids",
        score=88.5,
    )

    # 1. Verify Clean Master File & Sliced Transcript
    clip_dir = mgr.get_long_clip_dir(run_dir, 1)
    clean_master = clip_dir / "clip_01.mp4"
    transcript_file = clip_dir / "transcript.json"
    metadata_file = clip_dir / "metadata.json"

    assert clean_master.exists()
    assert transcript_file.exists()
    assert metadata_file.exists()

    # 2. Verify ClipMetadata
    loaded_meta = mgr.load_clip_metadata(clip_dir)
    assert loaded_meta.clip_id == "lng_001"
    assert loaded_meta.clip_type == "long"
    assert loaded_meta.parent_type == "source_video"
    assert loaded_meta.parent_id == "vid_20261024_01"
    assert loaded_meta.timeline.source_start_seconds == 11.73
    assert loaded_meta.timeline.source_end_seconds == 63.00
    assert loaded_meta.timeline.local_start_seconds == 0.0
    assert loaded_meta.timeline.local_end_seconds == 51.27
    assert loaded_meta.files.clean_master == "clip_01.mp4"
    assert loaded_meta.files.final_render is None

    # 3. Verify ManifestLongClipItem
    assert manifest_item.clip_id == "lng_001"
    assert manifest_item.clean_master_path == "long_clips/clip_01/clip_01.mp4"
    assert manifest_item.final_render_path is None
    assert manifest_item.duration_seconds == 51.27


# -----------------------------------------------------------------------------
# 5. CLI Long-Mode Discovery & Boundary Refinement Integration
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_run_candidate_discovery_cli_long_mode_vs_short_mode(tmp_path: Path, sample_source_transcript, monkeypatch):
    """Test that discover_candidates CLI in long mode uses long settings, prompt, and refinement."""
    from app.cli.discover_candidates import run_candidate_discovery
    from app.services.llm.base import LLMProvider
    from app.api.v1.schemas.candidates import LLMCandidateEvaluation, ScoreBreakdown, EvidenceItem, ConfidenceLabel

    t_file = tmp_path / "transcript.json"
    t_file.write_text(sample_source_transcript.model_dump_json(indent=2), encoding="utf-8")

    calls = []

    class MockDiscoveryProvider(LLMProvider):
        async def discover_and_evaluate(self, transcript_segments, editorial_goal, settings, custom_instructions=None, target_count=None, is_long_clip=False):
            calls.append({
                "is_long_clip": is_long_clip,
                "settings": settings,
                "target_count": target_count,
            })
            # Return an evaluation with a punchline at 59.42s
            return [
                LLMCandidateEvaluation(
                    start_seconds=11.73,
                    end_seconds=59.42,
                    hook="Jimmy competing with kids",
                    transcript_excerpt="I play for money too",
                    score_dimensions=ScoreBreakdown(
                        hook_strength=4.5,
                        completeness_coherence=4.5,
                        standalone_understandability=4.5,
                        goal_relevance=4.5,
                        goal_specific_impact=4.5,
                        specificity_insight=4.0,
                        pacing_conciseness=4.0,
                        ending_quality=4.5,
                    ),
                    rationale="Complete funny story arc",
                    evidence=[
                        EvidenceItem(start_seconds=11.73, end_seconds=15.0, quote="Thank you for being here"),
                        EvidenceItem(start_seconds=55.0, end_seconds=59.42, quote="I play for money too"),
                    ],
                    confidence_label=ConfidenceLabel.HIGH,
                )
            ]

    monkeypatch.setattr("app.cli.discover_candidates.get_llm_provider", lambda **kwargs: MockDiscoveryProvider())

    # 1. Test short mode call
    short_out = tmp_path / "short_run"
    await run_candidate_discovery(
        transcript_path=t_file,
        output_dir=short_out,
        mode="short",
    )
    assert calls[0]["is_long_clip"] is False
    assert calls[0]["settings"].min_duration_seconds == 10.0
    assert calls[0]["settings"].target_duration_seconds == 30.0
    assert calls[0]["settings"].max_duration_seconds == 60.0
    assert not (short_out / "boundary_refinement_audit.json").exists()

    # 2. Test long mode call
    long_out = tmp_path / "long_run"
    await run_candidate_discovery(
        transcript_path=t_file,
        output_dir=long_out,
        mode="long",
    )
    assert calls[1]["is_long_clip"] is True
    assert calls[1]["settings"].min_duration_seconds == 30.0
    assert calls[1]["settings"].target_duration_seconds == 90.0
    assert calls[1]["settings"].max_duration_seconds == 180.0
    assert (long_out / "boundary_refinement_audit.json").exists()

    # Load candidate artifact from long mode and verify refinement was applied
    import json
    cand_data = json.loads((long_out / "candidates.json").read_text(encoding="utf-8"))
    assert cand_data["candidates_count"] == 1
    refined_cand = cand_data["candidates"][0]
    # Snapped end should be extended beyond 59.42s into the laughter cushion (up to ~60.42s or 60.92s)
    assert refined_cand["end_seconds"] > 59.42
    assert refined_cand["duration_seconds"] > 47.69
