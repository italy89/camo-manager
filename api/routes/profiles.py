"""
Profile CRUD endpoints + proxy check.

Wraps manager.py functions:
  create_profile, list_profiles, get_profile, update_profile, delete_profile, summary
"""

import json
import httpx
from pathlib import Path
from typing import Any, Optional, Union

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api.deps import manager, PROFILES_DIR

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


# ──────────────────────────────────────────────
# Pydantic models
# ──────────────────────────────────────────────

class ProfileCreate(BaseModel):
    """Request body for creating a new profile."""
    name: str = Field(..., min_length=1, description="Unique profile name")
    proxy: Optional[Any] = Field(None, description="Proxy string or dict")
    proxy_type: str = Field("http", description="Proxy type: http or socks5")
    note: str = Field("", description="Optional note")
    tags: Optional[list[str]] = Field(None, description="List of tags")


class ProfileUpdate(BaseModel):
    """Request body for updating a profile. All fields optional."""
    proxy: Optional[Any] = None
    proxy_type: Optional[str] = None
    note: Optional[str] = None
    tags: Optional[list[str]] = None
    viewport: Optional[dict] = Field(None, description="Browser viewport {width, height}")


class BulkDeleteRequest(BaseModel):
    """Request body for bulk profile deletion."""
    names: list[str] = Field(..., min_length=1, description="List of profile names to delete")


class ProfileResponse(BaseModel):
    """Standard profile data returned by the API."""
    model_config = {"extra": "allow"}

    name: str
    proxy: Optional[Any] = None
    proxy_type: str = "http"
    note: str = ""
    tags: list[str] = []
    created_at: Optional[str] = None
    last_used: Optional[str] = None
    use_count: int = 0
    size_bytes: int = 0


class ProfileDetailResponse(ProfileResponse):
    """Profile data with session history."""
    history: list[dict] = []


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _read_history(name: str) -> list[dict]:
    """Read session history for a profile, handling both storage formats."""
    history_path = PROFILES_DIR / name / "history.json"
    if not history_path.exists():
        return []
    try:
        with open(history_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Handle both formats: plain list or {"sessions": list}
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "sessions" in data:
            return data["sessions"]
        return []
    except (json.JSONDecodeError, OSError):
        return []


import os

def _dir_size(path: Path) -> int:
    """Calculate total size of a directory in bytes."""
    total = 0
    try:
        for dirpath, _dirnames, filenames in os.walk(str(path)):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
    except OSError:
        pass
    return total


# ──────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────

@router.get(
    "",
    response_model=list[ProfileResponse],
    summary="List all profiles",
    description="Return all profiles. Optionally filter by tag.",
)
def list_profiles(tag: Optional[str] = None):
    """List all profiles, with optional tag filter."""
    try:
        profiles = manager.list_profiles(tag=tag)
        # Add size_bytes for each profile
        for p in profiles:
            profile_dir = PROFILES_DIR / p.get("name", "")
            if profile_dir.exists():
                p["size_bytes"] = _dir_size(profile_dir)
            else:
                p["size_bytes"] = 0
        return profiles
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "",
    response_model=ProfileResponse,
    status_code=201,
    summary="Create a new profile",
)
def create_profile(body: ProfileCreate):
    """Create a new browser profile with the given configuration."""
    try:
        profile = manager.create_profile(
            name=body.name,
            proxy=body.proxy,
            proxy_type=body.proxy_type,
            note=body.note,
            tags=body.tags,
        )
        return profile
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/export",
    summary="Export all profiles as JSON",
    description="Download all profile configs as a single JSON file.",
)
def export_profiles():
    """Export all profiles as a downloadable JSON file."""
    try:
        profiles = manager.list_profiles()
        content = json.dumps(profiles, indent=2, ensure_ascii=False, default=str)
        return JSONResponse(
            content=profiles,
            media_type="application/json",
            headers={
                "Content-Disposition": "attachment; filename=camo_profiles_export.json"
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/import",
    summary="Import profiles from JSON file",
    description="Upload a JSON file containing an array of profile objects to import.",
)
async def import_profiles(file: UploadFile = File(...)):
    """Import profiles from a JSON file upload.

    The file should contain a JSON array of profile objects, each with at least
    a 'name' field. Existing profiles will be skipped.
    """
    if not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Only .json files are accepted")

    try:
        raw = await file.read()
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON file: {e}")

    if not isinstance(data, list):
        raise HTTPException(status_code=400, detail="JSON root must be an array of profiles")

    created = []
    skipped = []
    errors = []

    for item in data:
        if not isinstance(item, dict) or "name" not in item:
            errors.append({"item": str(item)[:100], "error": "Missing 'name' field"})
            continue

        name = item["name"]
        try:
            manager.create_profile(
                name=name,
                proxy=item.get("proxy"),
                proxy_type=item.get("proxy_type", "http"),
                note=item.get("note", ""),
                tags=item.get("tags"),
            )
            created.append(name)
        except ValueError:
            # Profile already exists
            skipped.append(name)
        except Exception as e:
            errors.append({"name": name, "error": str(e)})

    return {
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "total_created": len(created),
        "total_skipped": len(skipped),
        "total_errors": len(errors),
    }


@router.post(
    "/bulk/delete",
    summary="Bulk delete profiles",
    description="Delete multiple profiles at once by providing a list of names.",
)
def bulk_delete_profiles(body: BulkDeleteRequest):
    """Delete multiple profiles in a single request."""
    deleted = []
    errors = []
    for name in body.names:
        try:
            manager.delete_profile(name)
            deleted.append(name)
        except ValueError as e:
            errors.append({"name": name, "error": str(e)})
        except Exception as e:
            errors.append({"name": name, "error": str(e)})

    return {
        "deleted": deleted,
        "errors": errors,
        "total_deleted": len(deleted),
        "total_errors": len(errors),
    }


@router.get(
    "/{name}",
    response_model=ProfileDetailResponse,
    summary="Get profile details",
    description="Return full profile config plus session history.",
)
def get_profile(name: str):
    """Get a single profile's config and session history."""
    try:
        profile = manager.get_profile(name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    history = _read_history(name)
    return {**profile, "history": history}


@router.put(
    "/{name}",
    response_model=ProfileResponse,
    summary="Update a profile",
)
def update_profile(name: str, body: ProfileUpdate):
    """Update an existing profile's configuration.

    Only provided (non-None) fields will be updated.
    """
    # Build kwargs from non-None fields only
    update_data = body.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        profile = manager.update_profile(name, **update_data)
        return profile
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/{name}",
    summary="Delete a profile",
    description="Move the profile to trash (recoverable).",
)
def delete_profile(name: str):
    """Delete a single profile by name (moved to .trash)."""
    try:
        manager.delete_profile(name)
        return {"message": f"Profile '{name}' deleted", "name": name}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────
# Proxy check
# ──────────────────────────────────────────────

def _build_proxy_url(proxy_data, proxy_type: str = "http") -> Optional[str]:
    """Build a proxy URL from stored proxy data (dict or string)."""
    if not proxy_data:
        return None

    if isinstance(proxy_data, dict):
        ptype = proxy_data.get("type", proxy_type) or "http"
        host = proxy_data.get("host", "")
        port = proxy_data.get("port", "")
        username = proxy_data.get("username", "")
        password = proxy_data.get("password", "")
        if not host:
            return None
        scheme = "socks5" if "socks" in ptype.lower() else "http"
        auth = f"{username}:{password}@" if username else ""
        return f"{scheme}://{auth}{host}:{port}"

    # String format: user:pass@host:port
    if isinstance(proxy_data, str):
        scheme = "socks5" if "socks" in proxy_type.lower() else "http"
        return f"{scheme}://{proxy_data}"

    return None


@router.get(
    "/{name}/check-proxy",
    summary="Check proxy status",
    description="Test proxy connectivity and return external IP + country info.",
)
def check_proxy(name: str):
    """Check if profile's proxy is alive. Returns IP, country, city."""
    try:
        profile = manager.get_profile(name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    proxy_data = profile.get("proxy")
    proxy_type = profile.get("proxy_type", "http")

    if not proxy_data:
        return {"status": "no_proxy", "message": "Profile has no proxy configured"}

    proxy_url = _build_proxy_url(proxy_data, proxy_type)
    if not proxy_url:
        return {"status": "invalid", "message": "Cannot parse proxy config"}

    try:
        with httpx.Client(proxy=proxy_url, timeout=15, verify=False) as client:
            resp = client.get("http://ip-api.com/json/?fields=status,message,country,countryCode,city,query")
            data = resp.json()

        if data.get("status") == "success":
            return {
                "status": "alive",
                "ip": data.get("query", ""),
                "country": data.get("country", ""),
                "country_code": data.get("countryCode", "").lower(),
                "city": data.get("city", ""),
            }
        else:
            return {
                "status": "alive",
                "ip": "unknown",
                "country": "",
                "country_code": "",
                "city": "",
                "message": data.get("message", ""),
            }
    except Exception as e:
        return {
            "status": "dead",
            "message": f"Proxy unreachable: {str(e)[:200]}",
        }
