"""
Flux (fal.ai) image generator (Step 5.5).
Uses Flux Dev image-to-image endpoint via fal-client SDK.
IP-Adapter strength 0.85 preserves jewelry detail.
"""
from __future__ import annotations

import asyncio
import io
import os

import httpx
from PIL import Image

from src.modules.images.base import (
    AbstractImageGenerator,
    ImageGenerationRequest,
    ImageGenerationResult,
)


async def _download_image(url: str) -> Image.Image:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(url)
        response.raise_for_status()
        return Image.open(io.BytesIO(response.content))


class FluxImageGenerator(AbstractImageGenerator):
    def __init__(self, api_key: str) -> None:
        os.environ["FAL_KEY"] = api_key

    async def generate(self, request: ImageGenerationRequest) -> list[ImageGenerationResult]:
        import fal_client  # type: ignore[import]

        ref_bytes = io.BytesIO()
        request.reference_image.save(ref_bytes, format="PNG")
        ref_bytes.seek(0)

        # fal_client.upload expects raw bytes, not a BytesIO (it calls len()).
        # It's a blocking network POST — run it off the event loop.
        ref_url = await asyncio.to_thread(
            fal_client.upload, ref_bytes.getvalue(), content_type="image/png"
        )

        result = await fal_client.run_async(
            "fal-ai/flux/dev/image-to-image",
            arguments={
                "image_url": ref_url,
                "prompt": f"{request.prompt}. {request.style_hint}",
                "strength": 0.85,
                "num_images": request.num_outputs,
                "seed": request.seed,
            },
        )

        results: list[ImageGenerationResult] = []
        for img_info in result.get("images", []):
            img = await _download_image(img_info["url"])
            results.append(
                ImageGenerationResult(
                    image=img,
                    model_name=self.model_name,
                    cost_estimate=self.cost_per_image,
                    metadata={
                        "prompt": request.prompt,
                        "seed": img_info.get("seed"),
                    },
                )
            )

        return results

    @property
    def model_name(self) -> str:
        return "flux-dev-img2img"

    @property
    def cost_per_image(self) -> float:
        return 0.025
