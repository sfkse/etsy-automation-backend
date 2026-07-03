"""
Rexven Product Scraper

Scrapes a Rexven product detail page to extract image URL, title, cost, and
metadata badges. Rexven is a Turkish jewelry supplier platform.

Note: If Rexven adds heavy client-side rendering in future, upgrade this to
use Playwright. For now httpx + BeautifulSoup covers the server-rendered content.
"""
from __future__ import annotations

import re

import httpx
import structlog
from bs4 import BeautifulSoup

_log = structlog.get_logger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}


def scrape_rexven_product(url: str, timeout: int = 20) -> dict:
    """
    Fetch a Rexven product page and return extracted metadata.

    Returns dict with keys:
      image_url, title_tr, title_en, cost_cents, premium_cost_cents,
      category, satisa_uygun, yeni

    Raises httpx.HTTPError on network failure, ValueError on parse failure.
    """
    with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=timeout) as client:
        resp = client.get(url)
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    return _parse_product_page(soup, url)


def _parse_product_page(soup: BeautifulSoup, url: str) -> dict:
    result: dict = {
        "image_url": None,
        "title_tr": None,
        "title_en": None,
        "cost_cents": None,
        "premium_cost_cents": None,
        "category": None,
        "satisa_uygun": False,
        "yeni": False,
    }

    # Product image — try multiple selectors
    for selector in [
        "img.product-main-image",
        "img.product-detail__image",
        ".product-image img",
        ".product-photo img",
        'img[alt*="ürün"]',
        'img[class*="product"]',
    ]:
        img = soup.select_one(selector)
        if img and img.get("src"):
            result["image_url"] = img["src"]
            if result["image_url"].startswith("//"):
                result["image_url"] = "https:" + result["image_url"]
            break

    # Fallback: look for Open Graph image
    if not result["image_url"]:
        og_img = soup.find("meta", property="og:image")
        if og_img:
            result["image_url"] = og_img.get("content")

    # Product title (Turkish)
    for selector in [
        "h1.product-title",
        "h1.product-name",
        ".product-detail h1",
        "h1",
    ]:
        el = soup.select_one(selector)
        if el and el.get_text(strip=True):
            result["title_tr"] = el.get_text(strip=True)
            break

    # Open Graph title fallback
    if not result["title_tr"]:
        og_title = soup.find("meta", property="og:title")
        if og_title:
            result["title_tr"] = og_title.get("content", "").strip()

    # Price — look for elements with price-like content
    for selector in [
        ".product-price",
        ".price",
        '[class*="price"]',
        ".product-cost",
    ]:
        el = soup.select_one(selector)
        if el:
            text = el.get_text(strip=True)
            cents = _parse_price_cents(text)
            if cents and cents > 0:
                result["cost_cents"] = cents
                break

    # Premium price (often shown as a second price)
    price_els = soup.select('[class*="price"]')
    prices = []
    for el in price_els:
        cents = _parse_price_cents(el.get_text(strip=True))
        if cents and cents > 0:
            prices.append(cents)
    if len(prices) >= 2:
        result["premium_cost_cents"] = min(prices)
        result["cost_cents"] = result["cost_cents"] or max(prices)

    # Category
    breadcrumbs = soup.select(".breadcrumb a, nav[aria-label*='bread'] a")
    if len(breadcrumbs) >= 2:
        result["category"] = breadcrumbs[-1].get_text(strip=True)

    # Badges — look for red/special badge text
    page_text = soup.get_text()
    if "satışa uygun" in page_text.lower() or "satisa uygun" in page_text.lower():
        result["satisa_uygun"] = True
    if re.search(r"\byeni\b", page_text.lower()):
        result["yeni"] = True

    _log.info(
        "rexven_scrape_complete",
        url=url,
        has_image=bool(result["image_url"]),
        title=result["title_tr"],
        cost_cents=result["cost_cents"],
    )

    return result


def _parse_price_cents(text: str) -> int | None:
    """Extract price in cents from a price string like '$7.38' or '7,38 ₺'."""
    if not text:
        return None
    # Strip currency symbols and whitespace
    cleaned = re.sub(r"[^\d.,]", "", text.strip())
    if not cleaned:
        return None
    # Normalise decimal separator — last "." or "," is decimal
    cleaned = cleaned.replace(",", ".")
    # If multiple dots, keep only last as decimal separator
    parts = cleaned.rsplit(".", 1)
    if len(parts) == 2:
        integer_part = parts[0].replace(".", "")
        decimal_part = parts[1][:2]
        try:
            dollars = int(integer_part or "0")
            cents = int(decimal_part.ljust(2, "0"))
            return dollars * 100 + cents
        except ValueError:
            return None
    else:
        try:
            return int(cleaned.replace(".", "")) * 100
        except ValueError:
            return None
