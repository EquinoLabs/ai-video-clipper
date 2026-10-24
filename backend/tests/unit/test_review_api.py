"""Unit and API tests for Phase 3 review endpoints, media streaming, and security checks."""

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.api.v1.schemas.candidates import (
    CandidateListItem,
    CandidateStatus,
    ConfidenceLabel,
    EditorialGoal,
    EvidenceItem,
    GenerationSettings,
    ScoreBreakdown,
    ValidationStatus,
)
from app.domain.candidates.models import (
    CandidateArtifact,
    CandidateGenerationMetadata,
    write_candidate_artifact,
)
from app.domain.transcript.models import SourceMediaMetadata
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def setup_test_run(tmp_path: Path, monkeypatch):
    """Create a temporary outputs directory structure with a candidate and rendered file."""
    fake_outputs = tmp_path / "outputs"
    fake_outputs.mkdir()
    run_dir = fake_outputs / "run_test_001"
    run_dir.mkdir()
    rendered_dir = run_dir / "rendered_clips"
    rendered_dir.mkdir()

    # Monkeypatch OUTPUTS_BASE_DIR in review module
    monkeypatch.setattr("app.api.v1.routes.review.OUTPUTS_BASE_DIR", fake_outputs)

    # Create dummy rendered clip
    dummy_clip = rendered_dir / "cnd_001_10.0s_25.0s.mp4"
    dummy_clip.write_bytes(b"fake_mp4_bytes")

    dummy_ass = rendered_dir / "cnd_001_10.0s_25.0s.ass"
    dummy_ass.write_text("[Script Info]\nTitle: Test", encoding="utf-8")

    # Create candidate artifact
    cands = [
        CandidateListItem(
            id="cnd_001",
            start_seconds=10.0,
            end_seconds=25.0,
            duration_seconds=15.0,
            hook="Test candidate hook",
            transcript_excerpt="Test transcript excerpt...",
            editorial_goal=EditorialGoal.EDUCATION,
            overall_score=85,
            score_breakdown=ScoreBreakdown(
                hook_strength=4.5, completeness_coherence=4.0, standalone_understandability=4.0,
                goal_relevance=4.5, goal_specific_impact=4.0, specificity_insight=4.5,
                pacing_conciseness=4.0, ending_quality=4.0,
            ),
            rationale="Great testing moment.",
            evidence=[EvidenceItem(start_seconds=10.0, end_seconds=15.0, quote="Test excerpt")],
            confidence_label=ConfidenceLabel.HIGH,
            validation_status=ValidationStatus.VALID,
            selected=False,
            status=CandidateStatus.SUGGESTED,
        ),
        CandidateListItem(
            id="cnd_002",
            start_seconds=30.0,
            end_seconds=45.0,
            duration_seconds=15.0,
            hook="Unrendered moment",
            transcript_excerpt="Unrendered excerpt...",
            editorial_goal=EditorialGoal.EDUCATION,
            overall_score=75,
            score_breakdown=ScoreBreakdown(
                hook_strength=3.5, completeness_coherence=3.5, standalone_understandability=3.5,
                goal_relevance=3.5, goal_specific_impact=3.5, specificity_insight=3.5,
                pacing_conciseness=3.5, ending_quality=3.5,
            ),
            rationale="Unrendered.",
            evidence=[],
            confidence_label=ConfidenceLabel.MEDIUM,
            validation_status=ValidationStatus.VALID,
            selected=False,
            status=CandidateStatus.SUGGESTED,
        ),
    ]

    artifact = CandidateArtifact(
        schema_version="v1.0",
        source_media=SourceMediaMetadata(
            filename="source_test.mp4",
            format_name="mov,mp4",
            duration_seconds=60.0,
            size_bytes=1024,
            video_streams_count=1,
            audio_streams_count=1,
            selected_audio_stream_index=0,
            audio_codec="aac",
            audio_sample_rate=44100,
            audio_channels=2,
        ),
        generation=CandidateGenerationMetadata(
            editorial_goal=EditorialGoal.EDUCATION,
            provider="openai",
            model="gpt-4o-mini",
            scoring_version="v1.0",
            settings=GenerationSettings(),
            chunks_processed=1,
            total_raw_candidates=2,
        ),
        candidates_count=2,
        candidates=cands,
    )

    write_candidate_artifact(artifact, run_dir / "candidates.json")
    return "run_test_001"


def test_list_runs_endpoint(client, setup_test_run):
    res = client.get("/api/v1/review/runs")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    run = data[0]
    assert run["run_id"] == "run_test_001"
    assert run["source_filename"] == "source_test.mp4"
    assert run["total_candidates"] == 2
    assert run["rendered_candidates"] == 1


def test_get_run_review_details_endpoint(client, setup_test_run):
    res = client.get(f"/api/v1/review/runs/{setup_test_run}")
    assert res.status_code == 200
    data = res.json()
    assert data["summary"]["run_id"] == setup_test_run
    candidates = data["candidates"]
    assert len(candidates) == 2

    # Candidate 1: rendered
    cand1 = candidates[0]
    assert cand1["id"] == "cnd_001"
    assert cand1["overall_score"] == 85
    assert cand1["render_info"]["is_rendered"] is True
    assert cand1["render_info"]["video_url"] == f"/api/v1/review/runs/{setup_test_run}/media/cnd_001_10.0s_25.0s.mp4"
    assert cand1["render_info"]["download_url"] == f"/api/v1/review/runs/{setup_test_run}/download/cnd_001_10.0s_25.0s.mp4"

    # Candidate 2: unrendered
    cand2 = candidates[1]
    assert cand2["id"] == "cnd_002"
    assert cand2["overall_score"] == 75
    assert cand2["render_info"]["is_rendered"] is False
    assert cand2["render_info"]["video_url"] is None


def test_serve_media_file_and_download(client, setup_test_run):
    # Media stream endpoint
    res = client.get(f"/api/v1/review/runs/{setup_test_run}/media/cnd_001_10.0s_25.0s.mp4")
    assert res.status_code == 200
    assert res.headers["content-type"] == "video/mp4"
    assert res.content == b"fake_mp4_bytes"

    # Download endpoint
    res_dl = client.get(f"/api/v1/review/runs/{setup_test_run}/download/cnd_001_10.0s_25.0s.mp4")
    assert res_dl.status_code == 200
    assert "attachment" in res_dl.headers.get("content-disposition", "") or "cnd_001_10.0s_25.0s.mp4" in res_dl.headers.get("content-disposition", "")


def test_security_path_traversal_rejection(client, setup_test_run):
    # Attempt directory traversal in run_id
    res = client.get("/api/v1/review/runs/..%2F..%2Fetc/passwd")
    assert res.status_code in [400, 403, 404]

    # Attempt directory traversal in filename
    res2 = client.get(f"/api/v1/review/runs/{setup_test_run}/media/..%2F..%2Fsecret.txt")
    assert res2.status_code in [400, 403, 404]


def test_nonexistent_run_returns_404(client, setup_test_run):
    res = client.get("/api/v1/review/runs/nonexistent_run_12345")
    assert res.status_code == 404
    assert "not found" in res.json()["error"]["message"].lower()
