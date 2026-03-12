"""
CamoManager Web UI — FastAPI Backend
=====================================
Main application entry point.

- Registers all API route modules
- Configures CORS for local development
- Mounts static files from web/dist for the SPA frontend
- Provides a catch-all fallback to serve index.html for client-side routing
- Runs with uvicorn on 0.0.0.0:8000
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from api.routes import profiles, browser, system

# ──────────────────────────────────────────────
# App
# ──────────────────────────────────────────────

app = FastAPI(
    title="CamoManager API",
    description="Multi-profile Camoufox browser management API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# ──────────────────────────────────────────────
# CORS — allow everything for local dev
# ──────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────

app.include_router(profiles.router)
app.include_router(browser.router)
app.include_router(system.router)


# ──────────────────────────────────────────────
# Health check
# ──────────────────────────────────────────────

@app.get("/api/health", tags=["system"], summary="Health check")
def health_check():
    """Simple health check endpoint."""
    return {"status": "ok", "service": "camo-manager"}


# ──────────────────────────────────────────────
# Static files & SPA fallback
# ──────────────────────────────────────────────

STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "dist"

if STATIC_DIR.exists():
    # Mount static assets (JS, CSS, images, etc.)
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(request: Request, full_path: str):
        """Serve the SPA index.html for any non-API route.

        This enables client-side routing — the React/Vue app handles the URL.
        API routes are matched first because they are registered before this catch-all.
        """
        # If the path points to an actual file in dist/, serve it directly
        file_path = STATIC_DIR / full_path
        if full_path and file_path.is_file():
            return FileResponse(str(file_path))
        # Otherwise, return index.html for client-side routing
        index = STATIC_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return JSONResponse(
            {"detail": "Frontend not built. Run 'npm run build' in web/"},
            status_code=404,
        )
else:
    @app.get("/", include_in_schema=False)
    def root():
        return {
            "message": "CamoManager API is running. Frontend not built yet.",
            "docs": "/api/docs",
        }


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=[str(Path(__file__).resolve().parent)],
    )
