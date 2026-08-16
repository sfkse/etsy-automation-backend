"""
Abstract image-to-video generator interface.
Mirrors ``modules.images.base`` — all video backends subclass AbstractVideoGenerator.

Unlike image generation (which passes a PIL image in memory), video providers here
fetch a **public image URL** and return the finished clip as raw ``.mp4`` bytes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class VideoGenerationRequest:
    image_url: str            # publicly-reachable URL of the source photo
    prompt: str               # motion / animation direction
    duration: int | None = None       # seconds; None = model default
    aspect_ratio: str | None = None   # e.g. "1:1", "9:16"; None = model default
    extra_params: dict = field(default_factory=dict)


@dataclass
class VideoGenerationResult:
    video_bytes: bytes
    model_name: str
    cost_estimate: float
    metadata: dict = field(default_factory=dict)


class AbstractVideoGenerator(ABC):
    @abstractmethod
    async def generate(self, request: VideoGenerationRequest) -> VideoGenerationResult:
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        ...

    @property
    @abstractmethod
    def cost_per_clip(self) -> float:
        ...
