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
    # Backends that let the model choose a ratio will drift to landscape on any
    # prompt that reads as a wide scene (an overhead flat lay, "generous empty
    # space"), and the pipeline letterboxes that onto its square canvas with
    # white bars rather than cropping it. Pin it instead of fighting it with
    # prompt wording. Etsy listings want square; "1:1" matches
    # ``pipeline.TARGET_SIZE`` exactly, so nothing is padded.
    aspect_ratio: str = "1:1"
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
