"""Timeline models and coordinate conversion primitives.

Hierarchy and coordinate semantics:
- Source video: root timeline (0.0 to source_duration).
- Long clip: tier-1 child of source video.
    Starts at source_start_seconds, ends at source_end_seconds.
    Local start is 0.0, local end is duration_seconds.
- Short clip: tier-2 child, cut from a parent long clip.
    local_start_seconds and local_end_seconds are offsets relative to the parent long clip master.
    source_start_seconds and source_end_seconds are offsets relative to the original source video.
"""

import math
from typing import Optional
from pydantic import BaseModel, Field, model_validator


class TimelineBoundsError(ValueError):
    """Raised when timeline coordinates violate duration or boundary bounds."""
    pass


def _ensure_finite(**kwargs: Optional[float]) -> None:
    """Validate that all provided numeric arguments are finite (not NaN, +inf, or -inf)."""
    for name, val in kwargs.items():
        if val is not None and not math.isfinite(val):
            raise TimelineBoundsError(f"{name} must be a finite number; got {val}")


class ClipTimeline(BaseModel):
    """Canonical clip timeline interval with source and parent-local coordinates."""
    source_start_seconds: float = Field(..., ge=0.0, description="Start offset relative to source video (seconds)")
    source_end_seconds: float = Field(..., ge=0.0, description="End offset relative to source video (seconds)")
    local_start_seconds: float = Field(..., ge=0.0, description="Start offset relative to immediate parent (seconds)")
    local_end_seconds: float = Field(..., ge=0.0, description="End offset relative to immediate parent (seconds)")
    duration_seconds: float = Field(..., gt=0.0, description="Clip duration in seconds (end - start)")

    @model_validator(mode="after")
    def validate_timeline(self) -> "ClipTimeline":
        _ensure_finite(
            source_start_seconds=self.source_start_seconds,
            source_end_seconds=self.source_end_seconds,
            local_start_seconds=self.local_start_seconds,
            local_end_seconds=self.local_end_seconds,
            duration_seconds=self.duration_seconds,
        )

        if self.source_end_seconds <= self.source_start_seconds:
            raise TimelineBoundsError(
                f"source_end_seconds ({self.source_end_seconds}) must be strictly greater than "
                f"source_start_seconds ({self.source_start_seconds})"
            )
        if self.local_end_seconds <= self.local_start_seconds:
            raise TimelineBoundsError(
                f"local_end_seconds ({self.local_end_seconds}) must be strictly greater than "
                f"local_start_seconds ({self.local_start_seconds})"
            )

        source_dur = round(self.source_end_seconds - self.source_start_seconds, 3)
        local_dur = round(self.local_end_seconds - self.local_start_seconds, 3)
        if abs(source_dur - local_dur) > 0.005:
            raise TimelineBoundsError(
                f"Source duration ({source_dur}s) does not match local duration ({local_dur}s)"
            )
        if abs(self.duration_seconds - source_dur) > 0.01:
            object.__setattr__(self, "duration_seconds", source_dur)

        return self


def validate_interval(
    start_seconds: float,
    end_seconds: float,
    max_duration: Optional[float] = None,
    min_clip_duration: float = 0.0,
    max_clip_duration: Optional[float] = None,
) -> None:
    """Validate a time interval against negative times, inversions, and container bounds."""
    _ensure_finite(
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        max_duration=max_duration,
        min_clip_duration=min_clip_duration,
        max_clip_duration=max_clip_duration,
    )
    if start_seconds < 0.0:
        raise TimelineBoundsError(f"Start time ({start_seconds}s) cannot be negative.")
    if end_seconds <= start_seconds:
        raise TimelineBoundsError(
            f"End time ({end_seconds}s) must be strictly greater than start time ({start_seconds}s)."
        )
    dur = end_seconds - start_seconds
    if dur < min_clip_duration:
        raise TimelineBoundsError(
            f"Interval duration ({dur:.3f}s) is less than minimum duration ({min_clip_duration:.3f}s)."
        )
    if max_clip_duration is not None and dur > max_clip_duration + 0.001:
        raise TimelineBoundsError(
            f"Interval duration ({dur:.3f}s) exceeds maximum allowed duration ({max_clip_duration:.3f}s)."
        )
    if max_duration is not None and end_seconds > max_duration + 0.05:
        raise TimelineBoundsError(
            f"End time ({end_seconds}s) exceeds container duration ({max_duration}s)."
        )


def source_to_parent_local(
    source_time: float,
    parent_source_start: float,
    parent_source_end: Optional[float] = None,
) -> float:
    """Convert an absolute source video timestamp to parent-local coordinates.

    Formula: local_time = source_time - parent_source_start
    """
    _ensure_finite(
        source_time=source_time,
        parent_source_start=parent_source_start,
        parent_source_end=parent_source_end,
    )
    if parent_source_end is not None and parent_source_end <= parent_source_start:
        raise TimelineBoundsError(
            f"parent_source_end ({parent_source_end}) must be > parent_source_start ({parent_source_start})"
        )
    if source_time < parent_source_start - 0.001:
        raise TimelineBoundsError(
            f"source_time ({source_time:.3f}s) is before parent start ({parent_source_start:.3f}s)"
        )
    if parent_source_end is not None and source_time > parent_source_end + 0.001:
        raise TimelineBoundsError(
            f"source_time ({source_time:.3f}s) exceeds parent end ({parent_source_end:.3f}s)"
        )
    return round(source_time - parent_source_start, 3)


def parent_local_to_source(
    local_time: float,
    parent_source_start: float,
    parent_source_end: Optional[float] = None,
) -> float:
    """Convert a parent-local timestamp to absolute source video coordinates.

    Formula: source_time = parent_source_start + local_time
    """
    _ensure_finite(
        local_time=local_time,
        parent_source_start=parent_source_start,
        parent_source_end=parent_source_end,
    )
    if local_time < 0.0:
        raise TimelineBoundsError(f"local_time ({local_time:.3f}s) cannot be negative")
    if parent_source_end is not None:
        parent_duration = parent_source_end - parent_source_start
        if local_time > parent_duration + 0.001:
            raise TimelineBoundsError(
                f"local_time ({local_time:.3f}s) exceeds parent duration ({parent_duration:.3f}s)"
            )
    return round(parent_source_start + local_time, 3)


def nested_child_local_to_source(
    child_local_time: float,
    child_in_parent_start: float,
    parent_source_start: float,
    child_duration: Optional[float] = None,
    parent_duration: Optional[float] = None,
) -> float:
    """Convert a nested child-local timestamp (e.g. playback position inside a short clip)
    back to absolute source coordinates through the parent clip.

    parent_local_time = child_in_parent_start + child_local_time
    source_time = parent_source_start + parent_local_time
    """
    _ensure_finite(
        child_local_time=child_local_time,
        child_in_parent_start=child_in_parent_start,
        parent_source_start=parent_source_start,
        child_duration=child_duration,
        parent_duration=parent_duration,
    )
    if child_local_time < 0.0:
        raise TimelineBoundsError(f"child_local_time ({child_local_time:.3f}s) cannot be negative")
    if child_duration is not None and child_local_time > child_duration + 0.001:
        raise TimelineBoundsError(
            f"child_local_time ({child_local_time:.3f}s) exceeds child duration ({child_duration:.3f}s)"
        )
    parent_local_time = child_in_parent_start + child_local_time
    if parent_duration is not None and parent_local_time > parent_duration + 0.001:
        raise TimelineBoundsError(
            f"Derived parent local time ({parent_local_time:.3f}s) exceeds parent duration ({parent_duration:.3f}s)"
        )
    return round(parent_source_start + parent_local_time, 3)


def source_to_nested_child_local(
    source_time: float,
    child_in_parent_start: float,
    parent_source_start: float,
    child_duration: Optional[float] = None,
) -> float:
    """Convert an absolute source timestamp to child-local coordinates."""
    _ensure_finite(
        source_time=source_time,
        child_in_parent_start=child_in_parent_start,
        parent_source_start=parent_source_start,
        child_duration=child_duration,
    )
    child_source_start = parent_source_start + child_in_parent_start
    if source_time < child_source_start - 0.001:
        raise TimelineBoundsError(
            f"source_time ({source_time:.3f}s) is before child start ({child_source_start:.3f}s)"
        )
    local_offset = source_time - child_source_start
    if child_duration is not None and local_offset > child_duration + 0.001:
        raise TimelineBoundsError(
            f"source_time offset ({local_offset:.3f}s) exceeds child duration ({child_duration:.3f}s)"
        )
    return round(local_offset, 3)
