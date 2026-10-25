"""Unit tests for timeline models, coordinate conversion primitives, and boundaries."""

import pytest

from pydantic import ValidationError

from app.ai_clipper.domain.timeline.models import (
    ClipTimeline,
    TimelineBoundsError,
    nested_child_local_to_source,
    parent_local_to_source,
    source_to_nested_child_local,
    source_to_parent_local,
    validate_interval,
)


def test_source_to_parent_local_valid_and_bounds():
    # Long parent starts at 100.0, ends at 200.0
    parent_start = 100.0
    parent_end = 200.0

    # Boundary: at parent start -> 0.0
    assert source_to_parent_local(100.0, parent_start, parent_end) == 0.0

    # Middle: at 125.5 -> 25.5
    assert source_to_parent_local(125.5, parent_start, parent_end) == 25.5

    # Boundary: at parent end -> 100.0
    assert source_to_parent_local(200.0, parent_start, parent_end) == 100.0

    # Without upper bound specified
    assert source_to_parent_local(150.0, parent_start) == 50.0

    # Errors: before parent start
    with pytest.raises(TimelineBoundsError, match="before parent start"):
        source_to_parent_local(99.5, parent_start, parent_end)

    # Errors: after parent end
    with pytest.raises(TimelineBoundsError, match="exceeds parent end"):
        source_to_parent_local(200.5, parent_start, parent_end)

    # Errors: invalid parent bounds
    with pytest.raises(TimelineBoundsError, match="parent_source_end .* must be > parent_source_start"):
        source_to_parent_local(105.0, 100.0, 90.0)


def test_parent_local_to_source_valid_and_roundtrip():
    parent_start = 100.0
    parent_end = 200.0

    # Boundary: 0.0 -> 100.0
    assert parent_local_to_source(0.0, parent_start, parent_end) == 100.0

    # Offset: 25.5 -> 125.5
    assert parent_local_to_source(25.5, parent_start, parent_end) == 125.5

    # Roundtrip property
    for test_time in [100.0, 115.3, 150.0, 199.9, 200.0]:
        local = source_to_parent_local(test_time, parent_start, parent_end)
        recovered = parent_local_to_source(local, parent_start, parent_end)
        assert abs(recovered - test_time) < 0.001

    # Errors: negative local time
    with pytest.raises(TimelineBoundsError, match="cannot be negative"):
        parent_local_to_source(-1.0, parent_start, parent_end)

    # Errors: exceeds parent duration
    with pytest.raises(TimelineBoundsError, match="exceeds parent duration"):
        parent_local_to_source(105.0, parent_start, parent_end)


def test_nested_child_local_to_source_and_roundtrip():
    # Long parent: source 100.0 to 200.0 (duration 100.0)
    # Short clip: starts at parent local 15.0 (source 115.0), duration 30.0 (source 145.0)
    parent_start = 100.0
    child_in_parent_start = 15.0
    child_duration = 30.0

    # Playback start inside short (local 0.0) -> source 115.0
    assert nested_child_local_to_source(
        child_local_time=0.0,
        child_in_parent_start=child_in_parent_start,
        parent_source_start=parent_start,
        child_duration=child_duration,
    ) == 115.0

    # Playback middle inside short (local 10.5) -> source 125.5
    assert nested_child_local_to_source(
        child_local_time=10.5,
        child_in_parent_start=child_in_parent_start,
        parent_source_start=parent_start,
        child_duration=child_duration,
    ) == 125.5

    # Reverse mapping: source to nested child local
    assert source_to_nested_child_local(
        source_time=125.5,
        child_in_parent_start=child_in_parent_start,
        parent_source_start=parent_start,
        child_duration=child_duration,
    ) == 10.5

    # Out of bounds errors
    with pytest.raises(TimelineBoundsError, match="cannot be negative"):
        nested_child_local_to_source(-0.5, child_in_parent_start, parent_start, child_duration)

    with pytest.raises(TimelineBoundsError, match="exceeds child duration"):
        nested_child_local_to_source(35.0, child_in_parent_start, parent_start, child_duration)

    with pytest.raises(TimelineBoundsError, match="exceeds parent duration"):
        nested_child_local_to_source(
            child_local_time=20.0,
            child_in_parent_start=90.0,
            parent_source_start=100.0,
            parent_duration=100.0,  # 90 + 20 = 110 > 100
        )

    with pytest.raises(TimelineBoundsError, match="is before child start"):
        source_to_nested_child_local(
            source_time=110.0,
            child_in_parent_start=15.0,
            parent_source_start=100.0,  # child starts at 115.0
        )


def test_validate_interval():
    # Valid interval
    validate_interval(10.0, 40.0, max_duration=100.0, min_clip_duration=10.0, max_clip_duration=60.0)

    # Negative start
    with pytest.raises(TimelineBoundsError, match="cannot be negative"):
        validate_interval(-1.0, 10.0)

    # Inverted interval
    with pytest.raises(TimelineBoundsError, match="must be strictly greater"):
        validate_interval(20.0, 10.0)
    with pytest.raises(TimelineBoundsError, match="must be strictly greater"):
        validate_interval(20.0, 20.0)

    # Duration below minimum
    with pytest.raises(TimelineBoundsError, match="less than minimum duration"):
        validate_interval(10.0, 15.0, min_clip_duration=10.0)

    # Duration exceeds maximum
    with pytest.raises(TimelineBoundsError, match="exceeds maximum allowed duration"):
        validate_interval(10.0, 80.0, max_clip_duration=60.0)

    # Exceeds container bound
    with pytest.raises(TimelineBoundsError, match="exceeds container duration"):
        validate_interval(80.0, 110.0, max_duration=100.0)


def test_clip_timeline_model_validation():
    # Valid long clip timeline (local coordinates start at 0.0)
    tl_long = ClipTimeline(
        source_start_seconds=11.73,
        source_end_seconds=63.00,
        local_start_seconds=0.0,
        local_end_seconds=51.27,
        duration_seconds=51.27,
    )
    assert tl_long.duration_seconds == 51.27

    # Valid short clip timeline (child of long clip)
    tl_short = ClipTimeline(
        source_start_seconds=45.00,
        source_end_seconds=63.00,
        local_start_seconds=33.27,
        local_end_seconds=51.27,
        duration_seconds=18.00,
    )
    assert tl_short.duration_seconds == 18.00

    # Inverted source bounds
    with pytest.raises(ValidationError, match="source_end_seconds .* must be strictly greater than"):
        ClipTimeline(
            source_start_seconds=63.00,
            source_end_seconds=45.00,
            local_start_seconds=0.0,
            local_end_seconds=18.00,
            duration_seconds=18.00,
        )

    # Inverted local bounds
    with pytest.raises(ValidationError, match="local_end_seconds .* must be strictly greater than"):
        ClipTimeline(
            source_start_seconds=45.00,
            source_end_seconds=63.00,
            local_start_seconds=51.27,
            local_end_seconds=33.27,
            duration_seconds=18.00,
        )

    # Mismatch between source duration and local duration
    with pytest.raises(ValidationError, match="Source duration .* does not match local duration"):
        ClipTimeline(
            source_start_seconds=10.00,
            source_end_seconds=30.00,  # dur = 20.0s
            local_start_seconds=0.0,
            local_end_seconds=25.00,  # dur = 25.0s
            duration_seconds=20.00,
        )


def test_reject_non_finite_values_in_timeline_and_conversions():
    non_finite_values = [float("nan"), float("inf"), float("-inf")]

    # 1. validate_interval rejects NaN, +inf, -inf
    for bad_val in non_finite_values:
        with pytest.raises(TimelineBoundsError, match="must be a finite number"):
            validate_interval(bad_val, 10.0)
        with pytest.raises(TimelineBoundsError, match="must be a finite number"):
            validate_interval(0.0, bad_val)
        with pytest.raises(TimelineBoundsError, match="must be a finite number"):
            validate_interval(0.0, 10.0, max_duration=bad_val)
        with pytest.raises(TimelineBoundsError, match="must be a finite number"):
            validate_interval(0.0, 10.0, min_clip_duration=bad_val)
        with pytest.raises(TimelineBoundsError, match="must be a finite number"):
            validate_interval(0.0, 10.0, max_clip_duration=bad_val)

    # 2. ClipTimeline rejects NaN, +inf, -inf in all fields
    for bad_val in non_finite_values:
        with pytest.raises(ValidationError, match="must be a finite number|greater_than_equal"):
            ClipTimeline(
                source_start_seconds=bad_val,
                source_end_seconds=60.0,
                local_start_seconds=0.0,
                local_end_seconds=60.0,
                duration_seconds=60.0,
            )
        with pytest.raises(ValidationError, match="must be a finite number|greater_than_equal"):
            ClipTimeline(
                source_start_seconds=0.0,
                source_end_seconds=bad_val,
                local_start_seconds=0.0,
                local_end_seconds=60.0,
                duration_seconds=60.0,
            )
        with pytest.raises(ValidationError, match="must be a finite number|greater_than_equal"):
            ClipTimeline(
                source_start_seconds=0.0,
                source_end_seconds=60.0,
                local_start_seconds=bad_val,
                local_end_seconds=60.0,
                duration_seconds=60.0,
            )
        with pytest.raises(ValidationError, match="must be a finite number|greater_than_equal"):
            ClipTimeline(
                source_start_seconds=0.0,
                source_end_seconds=60.0,
                local_start_seconds=0.0,
                local_end_seconds=bad_val,
                duration_seconds=60.0,
            )
        with pytest.raises(ValidationError, match="must be a finite number|greater_than"):
            ClipTimeline(
                source_start_seconds=0.0,
                source_end_seconds=60.0,
                local_start_seconds=0.0,
                local_end_seconds=60.0,
                duration_seconds=bad_val,
            )

    # 3. Conversion helpers reject NaN, +inf, -inf
    for bad_val in non_finite_values:
        with pytest.raises(TimelineBoundsError, match="must be a finite number"):
            source_to_parent_local(bad_val, 100.0)
        with pytest.raises(TimelineBoundsError, match="must be a finite number"):
            source_to_parent_local(150.0, bad_val)
        with pytest.raises(TimelineBoundsError, match="must be a finite number"):
            source_to_parent_local(150.0, 100.0, parent_source_end=bad_val)

        with pytest.raises(TimelineBoundsError, match="must be a finite number"):
            parent_local_to_source(bad_val, 100.0)
        with pytest.raises(TimelineBoundsError, match="must be a finite number"):
            parent_local_to_source(20.0, bad_val)
        with pytest.raises(TimelineBoundsError, match="must be a finite number"):
            parent_local_to_source(20.0, 100.0, parent_source_end=bad_val)

        with pytest.raises(TimelineBoundsError, match="must be a finite number"):
            nested_child_local_to_source(bad_val, 15.0, 100.0)
        with pytest.raises(TimelineBoundsError, match="must be a finite number"):
            nested_child_local_to_source(5.0, bad_val, 100.0)
        with pytest.raises(TimelineBoundsError, match="must be a finite number"):
            nested_child_local_to_source(5.0, 15.0, bad_val)

        with pytest.raises(TimelineBoundsError, match="must be a finite number"):
            source_to_nested_child_local(bad_val, 15.0, 100.0)
        with pytest.raises(TimelineBoundsError, match="must be a finite number"):
            source_to_nested_child_local(120.0, bad_val, 100.0)
        with pytest.raises(TimelineBoundsError, match="must be a finite number"):
            source_to_nested_child_local(120.0, 15.0, bad_val)

