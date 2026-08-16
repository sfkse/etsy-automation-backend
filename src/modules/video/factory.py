"""
Video workflow factory & selector.
Returns the correct AbstractVideoGenerator for a given workflow name.
Mirrors ``modules.images.factory.ImageWorkflowFactory``.

Both workflows are Higgsfield-platform models (same auth/lifecycle) differing
only in endpoint and accepted body fields:
  - "dop"   → DoP standard: highest quality, fixed ~5s clip (no duration knob).
  - "kling" → Kling v2.1 pro: supports duration ∈ {5, 10} seconds.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.modules.video.base import AbstractVideoGenerator
from src.modules.video.higgsfield_generator import (
    _DOP_ENDPOINT,
    _KLING_ENDPOINT,
    HiggsfieldVideoGenerator,
)

if TYPE_CHECKING:
    from src.config.settings import Settings

# workflow name -> config for the shared Higgsfield generator
_MODELS: dict[str, dict] = {
    "dop": {
        "endpoint": _DOP_ENDPOINT,
        "model_name": "higgsfield-dop-standard",
        "allowed_durations": frozenset(),          # fixed length
        "cost_per_clip": 0.30,
    },
    "kling": {
        "endpoint": _KLING_ENDPOINT,
        "model_name": "kling-v2.1-pro",
        "allowed_durations": frozenset({5, 10}),
        "cost_per_clip": 0.40,
    },
}

# Durations offered in the UI per workflow (empty = model is fixed-length).
DURATION_OPTIONS: dict[str, list[int]] = {
    name: sorted(cfg["allowed_durations"]) for name, cfg in _MODELS.items()
}


class VideoWorkflowFactory:
    @classmethod
    def get(cls, workflow_name: str, settings: "Settings") -> AbstractVideoGenerator:
        cfg = _MODELS.get(workflow_name)
        if cfg is None:
            raise ValueError(
                f"Unknown video workflow: {workflow_name!r}. "
                f"Valid options: {list(_MODELS)}"
            )
        return HiggsfieldVideoGenerator(
            settings.HIGGSFIELD_API_KEY_ID,
            settings.HIGGSFIELD_API_KEY_SECRET,
            endpoint=cfg["endpoint"],
            model_name=cfg["model_name"],
            allowed_durations=cfg["allowed_durations"],
            cost_per_clip=cfg["cost_per_clip"],
        )

    @classmethod
    def available_workflows(cls) -> list[str]:
        return list(_MODELS)
