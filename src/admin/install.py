#!/usr/bin/env python3
"""
Admin module installation - mounts admin routes onto LiteLLM's FastAPI app.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .routes import admin_router

logger = logging.getLogger(__name__)

_ADMIN_HTML: Optional[str] = None


def _load_admin_html() -> str:
    """Load the admin HTML template."""
    global _ADMIN_HTML
    if _ADMIN_HTML is not None:
        return _ADMIN_HTML

    template_path = Path(__file__).parent / "templates" / "admin.html"
    if template_path.is_file():
        _ADMIN_HTML = template_path.read_text(encoding="utf-8")
    else:
        _ADMIN_HTML = "<html><body><h1>Admin template not found</h1></body></html>"
    return _ADMIN_HTML


def install_admin(app: FastAPI) -> None:
    """Mount admin routes and static page onto LiteLLM's FastAPI app."""
    # Mount API routes
    app.include_router(admin_router)

    static_dir = Path(__file__).parent / "static"
    static_index = static_dir / "index.html"
    if static_index.is_file():
        app.mount("/admin/assets", StaticFiles(directory=str(static_dir / "assets")), name="admin-assets")

        @app.get("/admin", include_in_schema=False)
        @app.get("/admin/", include_in_schema=False)
        async def serve_admin_page():
            return HTMLResponse(content=static_index.read_text(encoding="utf-8"))

        logger.info("React admin management panel installed at /admin/")
        return

    html_content = _load_admin_html()

    @app.get("/admin", include_in_schema=False)
    @app.get("/admin/", include_in_schema=False)
    async def serve_admin_page():
        return HTMLResponse(content=html_content)

    logger.info("Admin management panel installed at /admin/")
