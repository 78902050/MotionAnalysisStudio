"""Gap-aware filters for scalar and vector trajectory components."""

from __future__ import annotations

import math
from collections.abc import Sequence


def filter_values(
    values: Sequence[float],
    filter_name: str | None,
    *,
    window: int = 3,
) -> tuple[float, ...]:
    normalized = tuple(float(value) for value in values)
    if filter_name is None:
        return normalized
    if filter_name not in {"moving_average", "median"}:
        raise ValueError(f"unsupported filter: {filter_name}")
    if not isinstance(window, int) or isinstance(window, bool) or window < 1:
        raise ValueError("filter window must be a positive integer")

    result = [float("nan")] * len(normalized)
    for start, end in _finite_segments(normalized):
        segment = normalized[start:end]
        for local_index in range(len(segment)):
            left = max(0, local_index - window // 2)
            right = min(len(segment), local_index + window // 2 + 1)
            sample = segment[left:right]
            if filter_name == "moving_average":
                result[start + local_index] = sum(sample) / len(sample)
            else:
                ordered = sorted(sample)
                middle = len(ordered) // 2
                result[start + local_index] = (
                    ordered[middle]
                    if len(ordered) % 2
                    else (ordered[middle - 1] + ordered[middle]) / 2.0
                )
    return tuple(result)


def _finite_segments(values: Sequence[float]) -> tuple[tuple[int, int], ...]:
    segments: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(values):
        if math.isfinite(value):
            if start is None:
                start = index
        elif start is not None:
            segments.append((start, index))
            start = None
    if start is not None:
        segments.append((start, len(values)))
    return tuple(segments)
