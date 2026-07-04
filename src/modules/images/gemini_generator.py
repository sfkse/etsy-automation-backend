"""
Gemini image generator (Step 5.3).
Uses Gemini 3 Pro Image ("Nano Banana Pro") image generation endpoint.
"""
from __future__ import annotations

import asyncio
import io

from PIL import Image

from src.modules.images.base import (
    AbstractImageGenerator,
    ImageGenerationRequest,
    ImageGenerationResult,
)


class GeminiImageGenerator(AbstractImageGenerator):
    def __init__(self, api_key: str) -> None:
        from google import genai  # type: ignore[import]

        self.client = genai.Client(api_key=api_key)

    async def generate(self, request: ImageGenerationRequest) -> list[ImageGenerationResult]:
        from google.genai import types  # type: ignore[import]

        ref_bytes = io.BytesIO()
        request.reference_image.save(ref_bytes, format="PNG")
        ref_bytes.seek(0)

        full_prompt = f"{request.prompt}\n\nStyle: {request.style_hint}"

        # The google-genai SDK call is synchronous/blocking — run it in a
        # threadpool so it doesn't freeze the asyncio event loop (which would
        # make the whole web server unresponsive during generation).
        response = await asyncio.to_thread(
            self.client.models.generate_content,
            model="gemini-3-pro-image",
            contents=[
                types.Part.from_bytes(data=ref_bytes.getvalue(), mime_type="image/png"),
                full_prompt,
            ],
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"],
            ),
        )

        results: list[ImageGenerationResult] = []
        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                img = Image.open(io.BytesIO(part.inline_data.data))
                results.append(
                    ImageGenerationResult(
                        image=img,
                        model_name=self.model_name,
                        cost_estimate=self.cost_per_image,
                        metadata={"prompt": full_prompt},
                    )
                )

        return results

    @property
    def model_name(self) -> str:
        return "gemini-3-pro-image"

    @property
    def cost_per_image(self) -> float:
        return 0.039
