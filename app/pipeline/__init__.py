"""Pipeline dependency and execution contracts."""

from .dependency_graph import STAGES, StageGraph, invalidate_manifest

__all__ = ["STAGES", "StageGraph", "invalidate_manifest"]
