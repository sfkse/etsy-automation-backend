"""
Etsy Admin Routes (Phase 8)

GET  /admin/etsy               — dashboard: connection status + publish controls
GET  /admin/etsy/connect       — Step 8.1: initiate OAuth PKCE flow
GET  /admin/etsy/callback      — Step 8.1: OAuth callback, exchange code
POST /admin/etsy/publish       — Step 8.8: bulk publish approved products
POST /admin/etsy/disconnect    — remove stored token
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from src.config.settings import Settings
from src.db.dependencies import get_session
from src.db.models import Product, ProductStatus
from src.modules.etsy.client import EtsyClient
from src.modules.etsy.publisher import activate_listing_for_region, build_full_listing_payload, bulk_publish
from src.modules.etsy.token_manager import TokenManager

_log = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin/etsy", tags=["etsy"])
templates: Jinja2Templates | None = None

_settings = Settings()

# Process-level singletons — one token manager and client per worker process
_token_manager: TokenManager | None = None
_etsy_client: EtsyClient | None = None


def set_templates(t: Jinja2Templates) -> None:
    global templates
    templates = t


def _get_token_manager() -> TokenManager:
    global _token_manager
    if _token_manager is None:
        _token_manager = TokenManager(
            api_key=_settings.ETSY_API_KEY,
            redirect_uri=_settings.ETSY_REDIRECT_URI,
        )
    return _token_manager


def _get_etsy_client() -> EtsyClient:
    global _etsy_client
    if _etsy_client is None:
        _etsy_client = EtsyClient(
            token_manager=_get_token_manager(),
            shop_id=_settings.ETSY_SHOP_ID,
            api_key=_settings.ETSY_API_KEY,
            shared_secret=_settings.ETSY_SHARED_SECRET,
        )
    return _etsy_client


def _tmpl(name: str, request: Request, context: dict, **kwargs) -> HTMLResponse:
    return templates.TemplateResponse(request, name, context, **kwargs)


# ── Dashboard ──────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def etsy_dashboard(
    request: Request,
    session: Session = Depends(get_session),
):
    tm = _get_token_manager()
    connected = tm.is_connected()

    approved_count = (
        session.query(Product)
        .filter_by(status=ProductStatus.APPROVED.value)
        .count()
    )
    published_today = _count_published_today(session)

    from src.modules.etsy.publisher import _is_new_shop
    is_new = _is_new_shop(_settings.SHOP_CREATION_DATE)
    daily_limit = 15 if is_new else 50

    return _tmpl(
        "etsy/admin.html",
        request,
        {
            "connected": connected,
            "approved_count": approved_count,
            "published_today": published_today,
            "daily_limit": daily_limit,
            "remaining_today": max(0, daily_limit - published_today),
            "shop_id": _settings.ETSY_SHOP_ID,
            "publish_running": _publish_running,
        },
    )


# ── Step 8.1: Connect (initiate PKCE flow) ────────────────────────────────────

@router.get("/connect")
async def etsy_connect():
    """Redirect browser to Etsy OAuth authorization page."""
    if not _settings.ETSY_API_KEY:
        return JSONResponse(
            {"error": "ETSY_API_KEY is not configured in .env"},
            status_code=500,
        )
    tm = _get_token_manager()
    url = tm.get_auth_url()
    _log.info("Redirecting to Etsy OAuth", url=url[:80])
    return RedirectResponse(url=url, status_code=302)


# ── Step 8.1: Callback ────────────────────────────────────────────────────────

@router.get("/callback")
async def etsy_callback(code: str = "", state: str = "", error: str = ""):
    """Handle Etsy OAuth callback; exchange code for token."""
    if error:
        _log.warning("Etsy OAuth denied by user", error=error)
        return RedirectResponse(
            url="/admin/etsy?error=access_denied", status_code=302
        )

    if not code or not state:
        return RedirectResponse(
            url="/admin/etsy?error=missing_params", status_code=302
        )

    tm = _get_token_manager()
    success = await tm.exchange_code(code, state)

    if success:
        _log.info("Etsy OAuth successful")
        return RedirectResponse(url="/admin/etsy?connected=1", status_code=302)
    else:
        _log.error("Etsy OAuth code exchange failed")
        return RedirectResponse(
            url="/admin/etsy?error=exchange_failed", status_code=302
        )


# ── Step 8.8: Bulk publish ────────────────────────────────────────────────────

_publish_running: bool = False


@router.post("/publish")
async def etsy_bulk_publish(
    background_tasks: BackgroundTasks,
    skus_raw: str = Form(default=""),
    session: Session = Depends(get_session),
):
    """Kick off bulk publish in a background task."""
    global _publish_running
    if _publish_running:
        return JSONResponse({"error": "A publish run is already in progress."}, status_code=409)

    tm = _get_token_manager()
    if not tm.is_connected():
        return RedirectResponse(url="/admin/etsy?error=not_connected", status_code=302)

    approved_skus = (
        [s.strip() for s in skus_raw.split(",") if s.strip()]
        if skus_raw.strip()
        else None
    )

    background_tasks.add_task(
        _run_bulk_publish_bg,
        approved_skus=approved_skus,
    )

    return RedirectResponse(url="/admin/etsy?publishing=1", status_code=302)


async def _run_bulk_publish_bg(approved_skus: list[str] | None) -> None:
    global _publish_running
    _publish_running = True
    try:
        from src.db.session import SessionLocal

        with SessionLocal() as bg_session:
            result = await bulk_publish(
                client=_get_etsy_client(),
                session=bg_session,
                shipping_profiles=_settings.SHIPPING_PROFILES,
                return_policy_id=_settings.RETURN_POLICY_ID,
                shop_creation_date=_settings.SHOP_CREATION_DATE,
                approved_skus=approved_skus,
            )
            _log.info(
                "Bulk publish complete",
                published=len(result["published"]),
                errors=len(result["errors"]),
                skipped=result["skipped"],
            )
    except Exception as exc:
        _log.error("Bulk publish background task failed", error=str(exc))
    finally:
        _publish_running = False


# ── Manual activation (draft → active for one region) ───────────────────────────

@router.post("/activate/{sku}/{region}")
async def etsy_activate_region(
    sku: str,
    region: str,
    session: Session = Depends(get_session),
):
    """Explicit, user-triggered draft→active for one product's one region.

    Never called automatically — publish always stops at draft so the user
    can review on Etsy first.
    """
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return JSONResponse({"error": f"Unknown SKU: {sku}"}, status_code=404)

    try:
        listing_id = await activate_listing_for_region(_get_etsy_client(), product, region)
    except KeyError:
        return RedirectResponse(
            url=f"/products/{sku}?error=no_draft_for_region", status_code=302
        )
    except Exception as exc:
        _log.error("Manual activation failed", sku=sku, region=region, error=str(exc))
        return RedirectResponse(
            url=f"/products/{sku}?error=activate_failed", status_code=302
        )

    _log.info("Manually activated", sku=sku, region=region, listing_id=listing_id)
    return RedirectResponse(url=f"/products/{sku}?activated={region}", status_code=302)


# ── Payload preview (read-only, nothing sent) ───────────────────────────────────

@router.get("/preview/{sku}", response_class=HTMLResponse)
async def preview_payload(
    sku: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """Show the exact JSON that would be sent to Etsy for each shipping-
    profile region, without sending anything — built from the same
    build_full_listing_payload() the real publish path uses, so this can
    never drift from reality.
    """
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return RedirectResponse(url=f"/products/{sku}?error=not_found", status_code=302)

    tm = _get_token_manager()
    connected = tm.is_connected()
    previews = []
    if connected:
        client = _get_etsy_client()
        for region, shipping_profile_id in _settings.SHIPPING_PROFILES.items():
            payloads = await build_full_listing_payload(
                client, product, shipping_profile_id, _settings.RETURN_POLICY_ID,
                session=session, region=region,
            )
            previews.append({"region": region, **payloads})

    return _tmpl(
        "etsy/preview_payload.html", request,
        {
            "product": product,
            "connected": connected,
            "previews": previews,
        },
    )


# ── Disconnect ─────────────────────────────────────────────────────────────────

@router.post("/disconnect")
async def etsy_disconnect():
    _get_token_manager().disconnect()
    return RedirectResponse(url="/admin/etsy?disconnected=1", status_code=302)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _count_published_today(session: Session) -> int:
    from datetime import date, datetime

    today = date.today()
    return (
        session.query(Product)
        .filter(
            Product.status == ProductStatus.PUBLISHED.value,
            Product.published_at >= datetime(today.year, today.month, today.day),
        )
        .count()
    )
