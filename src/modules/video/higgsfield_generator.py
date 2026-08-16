"""
Higgsfield image-to-video generator (DoP model).

Higgsfield's REST API is asynchronous: submit a request, poll its ``status_url``
until it reaches a terminal state, then download the output ``.mp4``. All network
I/O is done with ``httpx.AsyncClient`` so it never blocks the event loop.

Two models are supported, both on the Higgsfield platform with identical auth and
lifecycle — they differ only in endpoint path and accepted body fields:
  - DoP   (POST /higgsfield-ai/dop/standard): highest quality, FIXED ~5s clip.
          ``duration`` is not a knob, so we don't send it.
  - Kling (POST /kling-video/v2.1/pro/image-to-video): supports ``duration`` ∈ {5, 10}.

Docs: https://docs.higgsfield.ai/docs
  - Base URL:  https://platform.higgsfield.ai
  - Auth:      Authorization: Key {API_KEY_ID}:{API_KEY_SECRET}
  - Body:      {image_url (required), prompt (required), duration? (model-dependent)}
  - Lifecycle: submit -> {status, request_id, status_url, cancel_url}; GET status_url
               until status is terminal; completed payload carries ``video.url``.
"""

from __future__ import annotations

import asyncio

import httpx

from src.modules.video.base import (
    AbstractVideoGenerator,
    VideoGenerationRequest,
    VideoGenerationResult,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

_BASE_URL = "https://platform.higgsfield.ai"
_DOP_ENDPOINT = f"{_BASE_URL}/higgsfield-ai/dop/standard"
_KLING_ENDPOINT = f"{_BASE_URL}/kling-video/v2.1/pro/image-to-video"

# Polling cadence — image-to-video can take several minutes (DoP standard).
# Poll every few seconds up to a generous ceiling so a stuck job can't spin
# forever, but a normal (slow) generation still has time to finish.
_POLL_INTERVAL_SECONDS = 5.0
_MAX_WAIT_SECONDS = 600.0  # 10 minutes

_TERMINAL_OK = {"completed"}
_TERMINAL_BAD = {"failed", "nsfw", "canceled"}

# Map Higgsfield's terse error codes to actionable messages.
_ERROR_HINTS = {
    "not_enough_credits": (
        "Higgsfield account is out of credits — top up at https://cloud.higgsfield.ai"
    ),
}


def _raise_for_status(resp: httpx.Response) -> None:
    """Like ``resp.raise_for_status()`` but include Higgsfield's response body.

    Higgsfield returns a JSON ``{"detail": "..."}`` on errors (e.g. a 403 with
    ``not_enough_credits``); the default httpx message hides it, so surface the
    real reason instead.
    """
    if resp.is_success:
        return
    detail = ""
    try:
        detail = str((resp.json() or {}).get("detail") or "").strip()
    except Exception:  # noqa: BLE001 — non-JSON body
        detail = (resp.text or "").strip()[:200]
    hint = _ERROR_HINTS.get(detail)
    msg = f"Higgsfield API {resp.status_code}"
    if detail:
        msg += f": {detail}"
    if hint:
        msg += f" ({hint})"
    raise RuntimeError(msg)


class HiggsfieldVideoGenerator(AbstractVideoGenerator):
    """One Higgsfield model, selected by endpoint.

    ``allowed_durations`` gates the ``duration`` body field: an empty set means
    the model has a fixed length (DoP) so we never send it; a non-empty set (e.g.
    ``{5, 10}`` for Kling) means we only forward a duration the model accepts and
    silently drop anything else so the request can't 400 on a bad value.
    """

    def __init__(
        self,
        api_key_id: str,
        api_key_secret: str,
        *,
        endpoint: str,
        model_name: str,
        allowed_durations: frozenset[int] = frozenset(),
        cost_per_clip: float = 0.30,
    ) -> None:
        if not api_key_id or not api_key_secret:
            raise ValueError(
                "Higgsfield credentials missing — set HIGGSFIELD_API_KEY_ID and "
                "HIGGSFIELD_API_KEY_SECRET in .env"
            )
        self._auth_header = f"Key {api_key_id}:{api_key_secret}"
        self._endpoint = endpoint
        self._model_name = model_name
        self._allowed_durations = allowed_durations
        self._cost_per_clip = cost_per_clip

    async def generate(self, request: VideoGenerationRequest) -> VideoGenerationResult:
        body: dict = {"image_url": request.image_url, "prompt": request.prompt}
        if request.duration is not None and request.duration in self._allowed_durations:
            body["duration"] = request.duration
        if request.aspect_ratio is not None:
            body["aspect_ratio"] = request.aspect_ratio
        body.update(request.extra_params)

        headers = {
            "Authorization": self._auth_header,
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            submit = await client.post(self._endpoint, headers=headers, json=body)
            _raise_for_status(submit)
            submitted = submit.json()

            status_url = submitted.get("status_url")
            request_id = submitted.get("request_id")
            if not status_url:
                raise RuntimeError(
                    f"Higgsfield submit returned no status_url: {submitted!r}"
                )
            logger.info("higgsfield_video_submitted", request_id=request_id)

            result = await self._poll_until_done(client, headers, status_url)
            video_url = (result.get("video") or {}).get("url")
            if not video_url:
                raise RuntimeError(
                    f"Higgsfield completed with no video url: {result!r}"
                )

            download = await client.get(video_url)
            download.raise_for_status()
            video_bytes = download.content

        return VideoGenerationResult(
            video_bytes=video_bytes,
            model_name=self.model_name,
            cost_estimate=self.cost_per_clip,
            metadata={"request_id": request_id, "prompt": request.prompt},
        )

    async def _poll_until_done(
        self,
        client: httpx.AsyncClient,
        headers: dict,
        status_url: str,
    ) -> dict:
        waited = 0.0
        status = "queued"
        while True:
            try:
                resp = await client.get(status_url, headers=headers)
                _raise_for_status(resp)
                data = resp.json()
                status = data.get("status")
                if status in _TERMINAL_OK:
                    return data
                if status in _TERMINAL_BAD:
                    raise RuntimeError(f"Higgsfield generation {status}: {data!r}")
            except httpx.RequestError as exc:
                # Transient network blip during a multi-minute poll — the job may
                # still be running on Higgsfield's side, so log and keep polling
                # rather than aborting. The max-wait ceiling still bounds this.
                logger.warning("higgsfield_poll_transient_error", error=str(exc))
            if waited >= _MAX_WAIT_SECONDS:
                raise TimeoutError(
                    f"Higgsfield generation still {status!r} after "
                    f"{int(_MAX_WAIT_SECONDS)}s"
                )
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            waited += _POLL_INTERVAL_SECONDS

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def cost_per_clip(self) -> float:
        # Higgsfield is credit-based; rough constant for display only.
        return self._cost_per_clip
