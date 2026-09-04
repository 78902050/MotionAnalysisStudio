"""Net semantic point changes between a saved pose baseline and current state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from app.domain.addresses import CorrectionTarget

PointValue = tuple[float, float, float]


@dataclass(frozen=True)
class PointChange:
    target: CorrectionTarget
    before: PointValue
    after: PointValue


@dataclass(frozen=True)
class ChangeSet:
    changes: tuple[PointChange, ...]

    @classmethod
    def between(
        cls,
        baseline: Mapping[CorrectionTarget, PointValue],
        current: Mapping[CorrectionTarget, PointValue],
    ) -> "ChangeSet":
        changes = tuple(
            PointChange(target, baseline[target], current[target])
            for target in baseline
            if target in current and baseline[target] != current[target]
        )
        return cls(changes)

    def __bool__(self) -> bool:
        return bool(self.changes)
