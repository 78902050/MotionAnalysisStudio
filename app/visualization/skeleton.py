"""Read semantic skeleton edges from Pose2Sim's installed model definitions."""

from __future__ import annotations

from collections.abc import Iterable


class SkeletonTopologyRepository:
    def __init__(self) -> None:
        self._models = self._load_models()

    @staticmethod
    def _load_models() -> dict[str, object]:
        try:
            from Pose2Sim import skeletons
        except ImportError:
            return {}
        models: dict[str, object] = {}
        for name in dir(skeletons):
            value = getattr(skeletons, name)
            if hasattr(value, "descendants") and hasattr(value, "name"):
                models[name.casefold()] = value
        return models

    def edges_for(
        self, model_name: str, keypoint_names: Iterable[str]
    ) -> tuple[tuple[str, str], ...]:
        model = self._models.get(str(model_name).strip().casefold())
        if model is None:
            return ()
        return self._edges_present_in(model, keypoint_names)

    def edges_for_labels(
        self, keypoint_names: Iterable[str]
    ) -> tuple[tuple[str, str], ...]:
        labels = {str(name).strip() for name in keypoint_names if str(name).strip()}
        if len(labels) < 4:
            return ()
        ranked: list[tuple[int, float, object]] = []
        seen_models: set[int] = set()
        for model in self._models.values():
            if id(model) in seen_models:
                continue
            seen_models.add(id(model))
            names = self._node_names(model)
            overlap = len(labels & names)
            if overlap < 4:
                continue
            ranked.append((overlap, overlap / max(len(names), 1), model))
        if not ranked:
            return ()
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        best = ranked[0]
        if len(ranked) > 1 and ranked[1][:2] == best[:2]:
            return ()
        if best[0] / len(labels) < 0.6:
            return ()
        return self._edges_present_in(best[2], labels)

    @staticmethod
    def _node_names(model: object) -> set[str]:
        nodes = (model, *getattr(model, "descendants", ()))
        return {str(getattr(node, "name", "")).strip() for node in nodes}

    @staticmethod
    def _edges_present_in(
        model: object, keypoint_names: Iterable[str]
    ) -> tuple[tuple[str, str], ...]:
        available = {str(name).strip() for name in keypoint_names}
        edges: list[tuple[str, str]] = []
        for child in getattr(model, "descendants", ()):
            parent = getattr(child, "parent", None)
            parent_name = str(getattr(parent, "name", "")).strip()
            child_name = str(getattr(child, "name", "")).strip()
            if parent_name in available and child_name in available:
                edges.append((parent_name, child_name))
        return tuple(edges)
