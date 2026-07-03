"""
Phase 4 — Vision-LLM Keyword Suggester (Layer A)

Given a Rexven product image, calls Claude Sonnet vision API to produce
15 keyword candidates (niche / medium / broad tiers) that an Etsy buyer
would actually type when searching for this product.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import anthropic
import structlog

from src.db.models import KeywordCandidate, KeywordTier, SourcingAnalysis, SourcingStatus
from src.config.settings import Settings

_log = structlog.get_logger(__name__)
_settings = Settings()

VISION_KEYWORD_PROMPT = """You are an Etsy SEO expert specializing in handmade jewelry.

I will show you a single jewelry product image from a Turkish supplier (Rexven). Your job is to predict how an American Etsy buyer would search for this exact product or very similar ones.

OUTPUT: a strict JSON object with three tiers of keywords.

TIER DEFINITIONS:
- "niche": 8-10 long-tail keywords (3-5 words each). These are specific, low-competition phrases an intentional buyer would type. Example: "dainty tennis racket pendant necklace", "sport themed gift for tennis player".
- "medium": 3-5 mid-tail keywords (2-3 words). These describe the product category clearly. Example: "tennis necklace", "minimalist sport jewelry".
- "broad": 1-2 high-volume head terms. These are competition giants — used only for context. Example: "gifts for her".

WHAT TO INFER FROM THE IMAGE:
1. Product form (what is it — pendant shape, chain style, earring type)
2. Material perception (gold-plated, silver, pearl, gemstone, enamel)
3. Style category (minimalist, boho, gothic, art deco, dainty, statement, vintage)
4. Theme or motif (animal, floral, religious, sport, celestial, alphabet/initial, birthstone)
5. Target recipient implied by style (mom, daughter, teen, bride, friend, pet owner)
6. Likely occasion (everyday, wedding, mother's day, christmas, valentine's, graduation, baptism)

CRITICAL RULES:
- Each keyword must be something a real buyer would type, not marketing copy.
- Do NOT include the words "Etsy", "handmade", or seller-side jargon.
- Each keyword max 30 characters.
- NICHE tier keywords must include at least 2 descriptive modifiers (style + form, or form + theme).
- For each keyword, give a one-sentence rationale tied to a visual feature.

ADDITIONAL CONTEXT (use to refine keyword choices):
- Supplier title (Turkish/English): {title}
- Supplier category: {category}
- Supplier cost: ${cost_usd}
- Premium pricing tier: ${premium_cost_usd}
- Supplier flagged this as a "Satışa Uygun" (sales-suitable) item: {satisa_uygun}

Return ONLY valid JSON in this exact shape (no markdown, no preamble):
{{
  "detected_attributes": {{
    "form": "...",
    "material": "...",
    "style": "...",
    "theme": "...",
    "recipient": "...",
    "occasion": "..."
  }},
  "niche": [
    {{"keyword": "...", "rationale": "..."}},
    ...
  ],
  "medium": [
    {{"keyword": "...", "rationale": "..."}},
    ...
  ],
  "broad": [
    {{"keyword": "...", "rationale": "..."}},
    ...
  ]
}}
"""


class VisionKeywordSuggester:
    """Layer A — produces keyword candidates from a Rexven product image."""

    MODEL = "claude-sonnet-4-5"

    def __init__(self, session, api_key: str | None = None):
        self.session = session
        self._client = anthropic.Anthropic(
            api_key=api_key or _settings.ANTHROPIC_API_KEY or None
        )

    def _encode_image(self, image_path: str) -> tuple[str, str]:
        """Return (base64_data, media_type)."""
        path = Path(image_path)
        suffix = path.suffix.lower()
        media_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }.get(suffix, "image/jpeg")

        with open(path, "rb") as f:
            data = base64.standard_b64encode(f.read()).decode("utf-8")
        return data, media_type

    def run(self, analysis: SourcingAnalysis) -> list[KeywordCandidate]:
        """Execute Layer A for a sourcing analysis. Persists candidates to DB."""
        analysis.status = SourcingStatus.LAYER_A_RUNNING.value
        self.session.commit()

        try:
            image_data, media_type = self._encode_image(analysis.image_path)

            prompt = VISION_KEYWORD_PROMPT.format(
                title=analysis.rexven_title_en or analysis.rexven_title_tr or "(not provided)",
                category=analysis.rexven_category or "jewelry",
                cost_usd=f"{(analysis.rexven_cost_usd_cents or 0) / 100:.2f}",
                premium_cost_usd=f"{(analysis.rexven_premium_cost_usd_cents or 0) / 100:.2f}",
                satisa_uygun="yes" if analysis.rexven_has_satisa_uygun_badge else "no",
            )

            response = self._client.messages.create(
                model=self.MODEL,
                max_tokens=2048,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }],
            )

            analysis.vision_tokens_used = (
                response.usage.input_tokens + response.usage.output_tokens
            )
            analysis.vision_cost_usd_cents = self._estimate_cost_cents(
                response.usage.input_tokens, response.usage.output_tokens
            )

            raw_text = response.content[0].text.strip()
            _log.info(
                "vision_llm_complete",
                analysis_id=analysis.id,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cost_cents=analysis.vision_cost_usd_cents,
            )

            parsed = self._parse_response(raw_text)
            candidates = self._persist_candidates(analysis, parsed)

            analysis.layer_a_completed = True
            self.session.commit()
            return candidates

        except Exception as e:
            analysis.status = SourcingStatus.FAILED.value
            analysis.error_message = f"Layer A failed: {str(e)}"
            self.session.commit()
            _log.exception("vision_keyword_suggester_failed", analysis_id=analysis.id)
            raise

    def _parse_response(self, raw_text: str) -> dict:
        """Strip markdown fences and parse JSON."""
        cleaned = raw_text
        for fence in ["```json", "```JSON", "```"]:
            cleaned = cleaned.replace(fence, "")
        cleaned = cleaned.strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Vision LLM returned malformed JSON: {e}\nRaw (first 500 chars): {raw_text[:500]}"
            ) from e

    def _persist_candidates(
        self, analysis: SourcingAnalysis, parsed: dict
    ) -> list[KeywordCandidate]:
        detected = parsed.get("detected_attributes", {})
        candidates = []

        for tier_key, tier_value in [
            ("niche", KeywordTier.NICHE.value),
            ("medium", KeywordTier.MEDIUM.value),
            ("broad", KeywordTier.BROAD.value),
        ]:
            for item in parsed.get(tier_key, []):
                kw = item.get("keyword", "").strip().lower()
                rationale = item.get("rationale", "").strip()

                if not kw or len(kw) > 100:
                    continue

                candidate = KeywordCandidate(
                    analysis_id=analysis.id,
                    keyword=kw,
                    tier=tier_value,
                    rationale=rationale,
                    detected_attributes=detected,
                    source_layer="A",
                )
                self.session.add(candidate)
                candidates.append(candidate)

        self.session.flush()
        return candidates

    @staticmethod
    def _estimate_cost_cents(input_tokens: int, output_tokens: int) -> int:
        """Rough estimate: $3/M input + $15/M output (Claude Sonnet pricing)."""
        cost_usd = (input_tokens / 1_000_000) * 3.0 + (output_tokens / 1_000_000) * 15.0
        return int(round(cost_usd * 100))
