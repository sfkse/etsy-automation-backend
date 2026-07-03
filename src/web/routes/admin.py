"""
Admin maintenance routes.

GET  /admin/cleanup — confirmation page showing current row counts per table.
POST /admin/cleanup — TRUNCATE every application table (preserves schema).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.db.dependencies import get_session
from src.db.session import Base

router = APIRouter(prefix="/admin", tags=["admin"])
templates: Jinja2Templates | None = None


def set_templates(t: Jinja2Templates) -> None:
    global templates
    templates = t


def _tmpl(name: str, request: Request, context: dict, **kwargs) -> HTMLResponse:
    return templates.TemplateResponse(request, name, context, **kwargs)


def _row_counts(session: Session) -> list[tuple[str, int]]:
    counts: list[tuple[str, int]] = []
    for tbl in Base.metadata.sorted_tables:
        n = session.execute(text(f'SELECT count(*) FROM "{tbl.name}"')).scalar() or 0
        counts.append((tbl.name, int(n)))
    return counts


@router.get("/cleanup", response_class=HTMLResponse)
async def cleanup_form(
    request: Request,
    session: Session = Depends(get_session),
):
    counts = _row_counts(session)
    total = sum(n for _, n in counts)
    wiped = request.query_params.get("wiped") == "1"
    return _tmpl(
        "admin/cleanup.html",
        request,
        {"counts": counts, "total": total, "wiped": wiped},
    )


@router.post("/cleanup", response_class=HTMLResponse)
async def cleanup_execute(session: Session = Depends(get_session)):
    table_names = ", ".join(
        f'"{tbl.name}"' for tbl in reversed(Base.metadata.sorted_tables)
    )
    session.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
    session.commit()
    return RedirectResponse(url="/admin/cleanup?wiped=1", status_code=303)
