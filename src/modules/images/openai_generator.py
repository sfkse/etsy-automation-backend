"""
OpenAI image generator (Step 5.4).
Uses gpt-image-1 via the images.edit endpoint for reference-based generation.
"""
from __future__ import annotations

import base64
import io

from PIL import Image

from src.modules.images.base import (
    AbstractImageGenerator,
    ImageGenerationRequest,
    ImageGenerationResult,
)


class OpenAIImageGenerator(AbstractImageGenerator):
    def __init__(self, api_key: str) -> None:
        from openai import OpenAI  # type: ignore[import]

        self.client = OpenAI(api_key=api_key)

    async def generate(self, request: ImageGenerationRequest) -> list[ImageGenerationResult]:
        ref_bytes = io.BytesIO()
        request.reference_image.save(ref_bytes, format="PNG")
        ref_bytes.seek(0)

        response = self.client.images.edit(
            model="gpt-image-1",
            image=ref_bytes,
            prompt=f"{request.prompt}. {request.style_hint}",
            n=request.num_outputs,
            size="1024x1024",
        )

        results: list[ImageGenerationResult] = []
        for img_data in response.data:
            raw = base64.b64decode(img_data.b64_json)
            img = Image.open(io.BytesIO(raw))
            results.append(
                ImageGenerationResult(
                    image=img,
                    model_name=self.model_name,
                    cost_estimate=self.cost_per_image,
                    metadata={"prompt": request.prompt},
                )
            )

        return results

    @property
    def model_name(self) -> str:
        return "gpt-image-1"

    @property
    def cost_per_image(self) -> float:
        return 0.04
