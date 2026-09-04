"""Persistent, explicitly confirmed person-association overrides."""

from __future__ import annotations

import json
from pathlib import Path

from app.io.atomic import AtomicJsonStore

from .model import AssociationCandidate, AssociationOverride, AssociationReport


class AssociationOverrideStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / "corrections" / "association_overrides.json"

    def load(self) -> tuple[AssociationOverride, ...]:
        if not self.path.is_file():
            return ()
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            raise ValueError("association overrides must be a list")
        return tuple(
            AssociationOverride.from_dict(item)
            for item in value
            if isinstance(item, dict)
        )

    def save_confirmed(
        self,
        candidate: AssociationCandidate,
        confirmed_by: str = "user",
    ) -> AssociationOverride:
        if not isinstance(candidate, AssociationCandidate):
            raise TypeError("candidate must be an AssociationCandidate")
        override = AssociationOverride.from_candidate(candidate, confirmed_by)
        overrides = [
            item
            for item in self.load()
            if (item.project_person_id, item.camera, item.synchronized_frame) != (
                override.project_person_id,
                override.camera,
                override.synchronized_frame,
            )
        ]
        overrides.append(override)
        AtomicJsonStore.replace(self.path, [item.to_dict() for item in overrides])
        return override

    def effective_constraints(
        self,
        report: AssociationReport,
    ) -> tuple[AssociationOverride, ...]:
        candidates = {item.candidate_id: item for item in report.candidates}
        effective: list[AssociationOverride] = []
        for override in self.load():
            match = next(
                (
                    candidate
                    for candidate in candidates.values()
                    if candidate.project_person_id == override.project_person_id
                    and candidate.camera == override.camera
                    and candidate.synchronized_frame == override.synchronized_frame
                    and candidate.raw_person_index == override.raw_person_index
                    and candidate.fingerprint.value_hash == override.fingerprint.value_hash
                ),
                None,
            )
            if match is not None:
                effective.append(override)
        return tuple(effective)
