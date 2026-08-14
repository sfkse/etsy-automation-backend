"""
Workflow factory & selector (Step 5.6).
Returns the correct AbstractImageGenerator for a given workflow name.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.modules.images.base import AbstractImageGenerator
from src.modules.images.gemini_generator import GeminiImageGenerator
from src.modules.images.openai_generator import OpenAIImageGenerator

if TYPE_CHECKING:
    from src.config.settings import Settings

_WORKFLOW_CLASSES: dict[str, type[AbstractImageGenerator]] = {
    "gemini": GeminiImageGenerator,
    "openai": OpenAIImageGenerator,
}


class ImageWorkflowFactory:
    @classmethod
    def get(cls, workflow_name: str, settings: "Settings") -> AbstractImageGenerator:
        if workflow_name not in _WORKFLOW_CLASSES:
            raise ValueError(
                f"Unknown workflow: {workflow_name!r}. "
                f"Valid options: {list(_WORKFLOW_CLASSES)}"
            )

        api_key_map = {
            "gemini": settings.GEMINI_API_KEY,
            "openai": settings.OPENAI_API_KEY,
        }
        return _WORKFLOW_CLASSES[workflow_name](api_key_map[workflow_name])

    @classmethod
    def get_all(cls, settings: "Settings") -> dict[str, AbstractImageGenerator]:
        return {name: cls.get(name, settings) for name in _WORKFLOW_CLASSES}

    @classmethod
    def available_workflows(cls) -> list[str]:
        return list(_WORKFLOW_CLASSES)
