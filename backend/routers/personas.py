"""
Personas router.
Handles custom AI persona management for system prompts.
"""

import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId

from database import get_database
from routers.auth import get_current_user
from models.persona import PersonaCreate, PersonaResponse, PersonaUpdate

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_model=List[PersonaResponse])
async def list_personas(current_user: dict = Depends(get_current_user)) -> dict:
    """List all personas for the user."""
    db = get_database()
    
    personas = []
    async for doc in db.personas.find({"userId": current_user["id"]}):
        personas.append(PersonaResponse(
            id=str(doc["_id"]),
            name=doc["name"],
            description=doc.get("description"),
            system_prompt=doc["systemPrompt"],
            is_default=doc.get("isDefault", False),
            created_at=doc["createdAt"],
            updated_at=doc["updatedAt"]
        ))
    
    return personas


@router.post("", response_model=PersonaResponse)
async def create_persona(
    data: PersonaCreate,
    current_user: dict = Depends(get_current_user)
) -> dict:
    """Create a new persona."""
    db = get_database()
    user_id = current_user["id"]
    
    now = datetime.utcnow()
    
    # If this is set as default, unset other defaults
    if data.is_default:
        await db.personas.update_many(
            {"userId": user_id},
            {"$set": {"isDefault": False}}
        )
    
    persona_doc = {
        "userId": user_id,
        "name": data.name,
        "description": data.description,
        "systemPrompt": data.system_prompt,
        "isDefault": data.is_default,
        "createdAt": now,
        "updatedAt": now
    }
    
    result = await db.personas.insert_one(persona_doc)
    
    return PersonaResponse(
        id=str(result.inserted_id),
        name=data.name,
        description=data.description,
        system_prompt=data.system_prompt,
        is_default=data.is_default,
        created_at=now,
        updated_at=now
    )


@router.get("/{persona_id}", response_model=PersonaResponse)
async def get_persona(
    persona_id: str,
    current_user: dict = Depends(get_current_user)
) -> dict:
    """Get a specific persona."""
    db = get_database()
    
    persona = await db.personas.find_one({
        "_id": ObjectId(persona_id),
        "userId": current_user["id"]
    })
    
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    
    return PersonaResponse(
        id=str(persona["_id"]),
        name=persona["name"],
        description=persona.get("description"),
        system_prompt=persona["systemPrompt"],
        is_default=persona.get("isDefault", False),
        created_at=persona["createdAt"],
        updated_at=persona["updatedAt"]
    )


@router.put("/{persona_id}", response_model=PersonaResponse)
async def update_persona(
    persona_id: str,
    data: PersonaUpdate,
    current_user: dict = Depends(get_current_user)
) -> dict:
    """Update a persona."""
    db = get_database()
    user_id = current_user["id"]
    
    # Build update document
    update_doc = {"updatedAt": datetime.utcnow()}
    
    if data.name is not None:
        update_doc["name"] = data.name
    if data.description is not None:
        update_doc["description"] = data.description
    if data.system_prompt is not None:
        update_doc["systemPrompt"] = data.system_prompt
    if data.is_default is not None:
        update_doc["isDefault"] = data.is_default
        # Unset other defaults if setting this as default
        if data.is_default:
            await db.personas.update_many(
                {"userId": user_id, "_id": {"$ne": ObjectId(persona_id)}},
                {"$set": {"isDefault": False}}
            )
    
    result = await db.personas.find_one_and_update(
        {"_id": ObjectId(persona_id), "userId": user_id},
        {"$set": update_doc},
        return_document=True
    )
    
    if not result:
        raise HTTPException(status_code=404, detail="Persona not found")
    
    return PersonaResponse(
        id=str(result["_id"]),
        name=result["name"],
        description=result.get("description"),
        system_prompt=result["systemPrompt"],
        is_default=result.get("isDefault", False),
        created_at=result["createdAt"],
        updated_at=result["updatedAt"]
    )


@router.delete("/{persona_id}")
async def delete_persona(
    persona_id: str,
    current_user: dict = Depends(get_current_user)
) -> dict:
    """Delete a persona."""
    db = get_database()
    
    result = await db.personas.delete_one({
        "_id": ObjectId(persona_id),
        "userId": current_user["id"]
    })
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Persona not found")
    
    return {"message": "Persona deleted"}
