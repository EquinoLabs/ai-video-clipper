"""Unit tests verifying the standard API error response envelope."""

import pytest
from app.api.v1.schemas.candidates import EvidenceItem, GenerationSettings


def test_evidence_item_rejects_reversed_timestamps():
    with pytest.raises(ValueError, match="end_seconds must be greater than start_seconds"):
        EvidenceItem(start_seconds=10.0, end_seconds=5.0, quote="Reversed timestamps")


def test_generation_settings_hierarchy_validation():
    with pytest.raises(ValueError, match="Duration hierarchy violated"):
        GenerationSettings(
            min_duration_seconds=30.0,
            preferred_min_seconds=15.0,  # Invalid: preferred_min < min
            preferred_max_seconds=45.0,
            max_duration_seconds=60.0,
        )
