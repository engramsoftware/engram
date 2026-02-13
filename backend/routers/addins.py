"""
Add-ins router.
Handles plugin installation, configuration, and management.
"""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from bson import ObjectId

from database import get_database
from routers.auth import get_current_user
from models.addin import AddinType, AddinResponse, AddinConfig

logger = logging.getLogger(__name__)
router = APIRouter()


class AddinInstallRequest(BaseModel):
    """Request to install a new add-in."""
    name: str
    description: Optional[str] = None
    addin_type: AddinType
    config: dict = {}
    permissions: List[str] = []


class AddinConfigUpdateRequest(BaseModel):
    """Request to update add-in configuration."""
    settings: dict = {}


def _to_str(val) -> str:
    """Convert a value to string, handling datetime objects from SQLite."""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val) if val else ""


def _doc_to_response(doc: dict) -> AddinResponse:
    """Convert a DB document to an AddinResponse."""
    return AddinResponse(
        id=str(doc["_id"]),
        name=doc.get("displayName") or doc["name"],
        internal_name=doc["name"],  # Manifest ID for frontend routing
        description=doc.get("description"),
        addin_type=doc["addinType"],
        enabled=doc.get("enabled", True),
        config=AddinConfig(settings=doc.get("config", {}).get("settings", {})),
        installed_at=_to_str(doc.get("installedAt", "")),
        version=doc.get("version", "1.0.0"),
        permissions=doc.get("permissions", []),
        built_in=doc.get("builtIn", False),
    )


@router.get("", response_model=List[AddinResponse])
async def list_addins(current_user: dict = Depends(get_current_user)) -> List[AddinResponse]:
    """List all installed add-ins for the user."""
    db = get_database()
    
    # Ensure all built-in addins exist for this user (seeds missing ones)
    try:
        from seed_addins import seed_built_in_addins_for_user
        await seed_built_in_addins_for_user(db, current_user["id"])
    except Exception as e:
        logger.warning(f"On-demand addin seeding failed: {e}")

    addins = []
    async for doc in db.addins.find({"userId": current_user["id"]}):
        addins.append(_doc_to_response(doc))
    
    return addins


@router.post("", response_model=AddinResponse)
async def install_addin(
    request: AddinInstallRequest,
    current_user: dict = Depends(get_current_user)
) -> AddinResponse:
    """Install a new add-in."""
    db = get_database()
    user_id = current_user["id"]
    
    # Check if already installed
    existing = await db.addins.find_one({
        "userId": user_id,
        "name": request.name
    })
    if existing:
        raise HTTPException(status_code=400, detail="Add-in already installed")
    
    # Create add-in document
    addin_doc = {
        "userId": user_id,
        "name": request.name,
        "description": request.description,
        "addinType": request.addin_type.value,
        "enabled": True,
        "config": {"settings": request.config},
        "installedAt": datetime.utcnow(),
        "version": "1.0.0",
        "permissions": request.permissions
    }
    
    result = await db.addins.insert_one(addin_doc)
    
    return AddinResponse(
        id=str(result.inserted_id),
        name=request.name,
        description=request.description,
        addin_type=request.addin_type,
        enabled=True,
        config=AddinConfig(settings=request.config),
        installed_at=_to_str(addin_doc["installedAt"]),
        version="1.0.0",
        permissions=request.permissions,
        built_in=False,
    )


@router.put("/{addin_id}/config", response_model=AddinResponse)
async def update_addin_config(
    addin_id: str,
    request: AddinConfigUpdateRequest,
    current_user: dict = Depends(get_current_user)
) -> AddinResponse:
    """Update add-in configuration."""
    db = get_database()
    
    result = await db.addins.find_one_and_update(
        {"_id": ObjectId(addin_id), "userId": current_user["id"]},
        {"$set": {"config.settings": request.settings}},
        return_document=True
    )
    
    if not result:
        raise HTTPException(status_code=404, detail="Add-in not found")
    
    return _doc_to_response(result)


@router.put("/{addin_id}/toggle", response_model=AddinResponse)
async def toggle_addin(
    addin_id: str,
    current_user: dict = Depends(get_current_user)
) -> AddinResponse:
    """Toggle add-in enabled/disabled state."""
    db = get_database()
    
    # Get current state
    addin = await db.addins.find_one({
        "_id": ObjectId(addin_id),
        "userId": current_user["id"]
    })
    
    if not addin:
        raise HTTPException(status_code=404, detail="Add-in not found")
    
    # Toggle
    new_state = not addin.get("enabled", True)
    
    result = await db.addins.find_one_and_update(
        {"_id": ObjectId(addin_id)},
        {"$set": {"enabled": new_state}},
        return_document=True
    )
    
    return _doc_to_response(result)


@router.delete("/{addin_id}")
async def uninstall_addin(
    addin_id: str,
    current_user: dict = Depends(get_current_user)
) -> dict:
    """Uninstall an add-in."""
    db = get_database()
    
    result = await db.addins.delete_one({
        "_id": ObjectId(addin_id),
        "userId": current_user["id"]
    })
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Add-in not found")
    
    return {"message": "Add-in uninstalled"}


class AddinActionRequest(BaseModel):
    """Request to invoke an addin action (dashboard, settings, etc.)."""
    action: str
    payload: dict = {}


@router.post("/{addin_name}/action")
async def addin_action(
    addin_name: str,
    request: AddinActionRequest,
    current_user: dict = Depends(get_current_user)
) -> dict:
    """
    Forward an action to a registered addin's handle_action method.

    This is the generic bridge between the frontend and any addin's
    backend logic — no hardcoding per addin. The addin declares what
    actions it supports via its own handle_action implementation.
    """
    try:
        from addins.registry import get_registry
        registry = get_registry()
        addin = registry.get_addin(addin_name)

        if not addin:
            raise HTTPException(status_code=404, detail=f"Add-in not found: {addin_name}")

        if not addin.enabled:
            raise HTTPException(status_code=400, detail=f"Add-in is disabled: {addin_name}")

        # Call the addin's handle_action if it has one
        if hasattr(addin, 'handle_action'):
            result = await addin.handle_action(request.action, request.payload)
            return result
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Add-in '{addin_name}' does not support actions"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Addin action failed ({addin_name}/{request.action}): {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{addin_name}/settings-schema")
async def get_addin_settings_schema(
    addin_name: str,
    current_user: dict = Depends(get_current_user)
) -> dict:
    """
    Get the settings schema for an addin.

    Addins declare their settings dynamically via get_settings_schema().
    The frontend reads this schema and renders appropriate controls
    WITHOUT any hardcoded addin-specific UI in the Settings page.

    Returns empty schema if the addin doesn't declare settings.
    """
    try:
        from addins.registry import get_registry
        registry = get_registry()
        addin = registry.get_addin(addin_name)

        if not addin:
            return {"sections": []}

        if hasattr(addin, 'get_settings_schema'):
            return addin.get_settings_schema()

        return {"addin_id": addin_name, "addin_name": addin.name, "sections": []}

    except Exception as e:
        logger.error(f"Failed to get settings schema for {addin_name}: {e}")
        return {"sections": []}
