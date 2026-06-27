"""
Abstract image generator interface (Step 5.1).
All AI image backends must subclass AbstractImageGenerator.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from PIL import Image


@dataclass
class ImageGenerationRequest:
    reference_image: Image.Image
    prompt: str
    style_hint: str
    num_outputs: int = 1
    seed: int | None = None
    extra_params: dict = field(default_factory=dict)


@dataclass
class ImageGenerationResult:
    image: Image.Image
    model_name: str
    cost_estimate: float
    metadata: dict = field(default_factory=dict)


class AbstractImageGenerator(ABC):
    @abstractmethod
    async def generate(self, request: ImageGenerationRequest) -> list[ImageGenerationResult]:
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        pass

    @property
    @abstractmethod
    def cost_per_image(self) -> float:
        pass
