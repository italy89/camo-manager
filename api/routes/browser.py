"""
Browser management endpoints.

Wraps browser_manager_v3.py BrowserManager methods:
  open_browser, close_browser, cmd, status, screenshot, close_all
"""

import tempfile
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api.deps import browser_manager, BrowserError, PROFILES_DIR

router = APIRouter(tags=["browser"])


# ──────────────────────────────────────────────
# Pydantic models
# ──────────────────────────────────────────────

class StartBrowserRequest(BaseModel):
    """Request body for starting a browser."""
    headless: Optional[bool] = Field(
        None,
        description="Run browser in headless mode. None = use profile default.",
    )


class BrowserStatusResponse(BaseModel):
    """Status of a single running browser."""
    alive: bool
    uptime: int = 0
    url: str = ""


# ──────────────────────────────────────────────
# Per-profile browser endpoints
# ──────────────────────────────────────────────

@router.post(
    "/api/profiles/{name}/start",
    summary="Start browser for profile",
    description="Launch a Camoufox browser instance using this profile's config.",
)
def start_browser(name: str, body: StartBrowserRequest = None):
    """Start a browser for the given profile.

    If the browser is already running, returns success without restarting.
    """
    if body is None:
        body = StartBrowserRequest()

    # Check profile exists first
    config_path = PROFILES_DIR / name / "config.json"
    if not config_path.exists():
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")

    try:
        success = browser_manager.open_browser(name, headless=body.headless)
        if not success:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to start browser for '{name}'. Check worker logs.",
            )
        return {
            "message": f"Browser started for '{name}'",
            "name": name,
            "status": "running",
        }
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/api/profiles/{name}/stop",
    summary="Stop browser for profile",
    description="Gracefully close the running browser for this profile.",
)
def stop_browser(name: str):
    """Stop the running browser for a profile."""
    try:
        browser_manager.close_browser(name)
        return {
            "message": f"Browser stopped for '{name}'",
            "name": name,
            "status": "stopped",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/api/profiles/{name}/status",
    response_model=BrowserStatusResponse,
    summary="Get browser status for profile",
    description="Check whether the browser is alive, its current URL, and uptime.",
)
def get_browser_status(name: str):
    """Get the runtime status of a profile's browser."""
    worker = browser_manager.workers.get(name)
    if not worker:
        return BrowserStatusResponse(alive=False, uptime=0, url="")

    # Process already dead?
    if not worker.alive:
        browser_manager.workers.pop(name, None)
        return BrowserStatusResponse(alive=False, uptime=0, url="")

    # Process alive — but is browser alive? Ping to find out.
    try:
        resp = worker.send({"action": "ping"}, timeout=5)
        if resp.get("status") == "error":
            # Process alive but browser dead (user closed window)
            w = browser_manager.workers.pop(name, None)
            if w:
                try:
                    w.process.terminate()
                except Exception:
                    pass
            return BrowserStatusResponse(alive=False, uptime=0, url="")
        url = resp.get("result", {}).get("url", "")
        return BrowserStatusResponse(
            alive=True,
            uptime=int(time.time() - worker.started_at),
            url=url,
        )
    except Exception:
        w = browser_manager.workers.pop(name, None)
        if w:
            try:
                w.process.terminate()
            except Exception:
                pass
        return BrowserStatusResponse(alive=False, uptime=0, url="")


@router.post(
    "/api/profiles/{name}/show",
    summary="Show browser window",
    description="Bring the browser window to the foreground (bring_to_front).",
)
def show_browser(name: str):
    """Bring the running browser window to the front."""
    worker = browser_manager.workers.get(name)
    if not worker or not worker.alive:
        # Clean up dead worker if exists
        browser_manager.workers.pop(name, None)
        raise HTTPException(
            status_code=404,
            detail=f"Browser for '{name}' is not running",
        )
    try:
        browser_manager.show_browser(name)
        return {"message": f"Browser '{name}' brought to front", "name": name}
    except BrowserError as e:
        # Browser died between check and command — clean up and return 404
        w = browser_manager.workers.pop(name, None)
        if w:
            try:
                w.process.terminate()
                w.process.wait(timeout=3)
            except Exception:
                try:
                    w.process.kill()
                except Exception:
                    pass
        raise HTTPException(
            status_code=404,
            detail=f"Browser for '{name}' was closed",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/api/profiles/{name}/screenshot",
    summary="Take screenshot",
    description="Capture a screenshot of the profile's browser and return it as a PNG image.",
    responses={
        200: {"content": {"image/png": {}}, "description": "Screenshot PNG image"},
        404: {"description": "Profile not found or browser not running"},
    },
)
def take_screenshot(name: str):
    """Take a screenshot of the current browser page and return the image."""
    worker = browser_manager.workers.get(name)
    if not worker or not worker.alive:
        raise HTTPException(
            status_code=404,
            detail=f"Browser for '{name}' is not running",
        )

    # Save screenshot to profile's screenshots directory
    ss_dir = PROFILES_DIR / name / "screenshots"
    ss_dir.mkdir(parents=True, exist_ok=True)
    ss_path = ss_dir / f"api_{int(time.time())}.png"

    try:
        browser_manager.screenshot(name, path=str(ss_path))
    except BrowserError as e:
        raise HTTPException(status_code=500, detail=f"Screenshot failed: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not ss_path.exists():
        raise HTTPException(status_code=500, detail="Screenshot file was not created")

    return FileResponse(
        path=str(ss_path),
        media_type="image/png",
        filename=f"{name}_screenshot.png",
    )


# ──────────────────────────────────────────────
# Global browser endpoints
# ──────────────────────────────────────────────

@router.get(
    "/api/browser/status",
    summary="All running browsers status",
    description="Return the status of every browser currently managed by the server.",
)
def all_browser_status():
    """Get status of all running browser instances."""
    try:
        status = browser_manager.status()
        return {
            "browsers": status,
            "total_running": sum(1 for v in status.values() if v.get("alive")),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/api/browser/stop-all",
    summary="Stop all browsers",
    description="Gracefully close every running browser instance.",
)
def stop_all_browsers():
    """Stop all running browsers."""
    try:
        # Collect names before closing so we can report them
        running = [
            name
            for name, w in browser_manager.workers.items()
            if w.alive
        ]
        browser_manager.close_all()
        return {
            "message": "All browsers stopped",
            "stopped": running,
            "total_stopped": len(running),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
