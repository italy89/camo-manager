"""
System-level endpoints: summary stats, tags.

Wraps manager.py: summary(), list_profiles()
"""

from fastapi import APIRouter, HTTPException

from api.deps import manager

router = APIRouter(tags=["system"])


@router.get(
    "/api/system/summary",
    summary="System summary",
    description="Return aggregate statistics: total profiles, proxy usage, tags, last activity.",
)
def system_summary():
    """Get a high-level summary of the CamoManager system."""
    try:
        return manager.summary()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/api/tags",
    summary="List all tags",
    description="Return a deduplicated, sorted list of every tag used across all profiles.",
)
def list_tags():
    """Collect all unique tags from every profile."""
    try:
        profiles = manager.list_profiles()
        all_tags = set()
        for p in profiles:
            for t in p.get("tags", []):
                all_tags.add(t)
        return {"tags": sorted(all_tags)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
