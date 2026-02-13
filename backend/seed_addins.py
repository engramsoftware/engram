"""
Seed built-in add-ins into the database.

Reads manifest.json files from addins/plugins/ and inserts them
into the addins collection for each user. Skips addins that are
already installed (matched by name + userId).

Called at startup from main.py lifespan, similar to seed_personas.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# Directory containing built-in addin folders with manifest.json
PLUGINS_DIR = Path(__file__).parent / "addins" / "plugins"


def _load_manifests() -> List[Dict[str, Any]]:
    """Load all manifest.json files from the plugins directory.

    Returns:
        List of parsed manifest dicts.
    """
    manifests = []
    if not PLUGINS_DIR.is_dir():
        logger.warning(f"Plugins directory not found: {PLUGINS_DIR}")
        return manifests

    for addin_dir in sorted(PLUGINS_DIR.iterdir()):
        manifest_path = addin_dir / "manifest.json"
        if addin_dir.is_dir() and manifest_path.is_file():
            try:
                with open(manifest_path, "r") as f:
                    manifest = json.load(f)
                # Validate required fields
                if all(k in manifest for k in ("id", "name", "type")):
                    manifests.append(manifest)
                else:
                    logger.warning(f"Skipping invalid manifest: {manifest_path}")
            except Exception as e:
                logger.warning(f"Failed to read manifest {manifest_path}: {e}")

    return manifests


async def seed_built_in_addins_for_user(db: Any, user_id: str) -> int:
    """Seed built-in add-ins for a single user.

    Inserts any built-in addins that aren't already installed for the
    given user. Built-in addins start as disabled so the user can
    enable them manually in the UI.

    Args:
        db: Database instance (SQLiteDatabase or MongoDB).
        user_id: The user ID to seed addins for.

    Returns:
        Number of addins seeded.
    """
    manifests = _load_manifests()
    if not manifests:
        return 0

    seeded = 0
    for manifest in manifests:
        # Check if already installed for this user
        existing = await db.addins.find_one({
            "userId": user_id,
            "name": manifest["id"],
        })
        if existing:
            # Re-seed if version changed (new features/config/icon)
            if existing.get("version") == manifest.get("version", "1.0.0"):
                # Check if icon metadata is present — if not, needs refresh
                cfg = existing.get("config", {}).get("settings", {})
                ui_meta = manifest.get("ui", {})
                if not ui_meta.get("icon") or cfg.get("icon") == ui_meta.get("icon"):
                    continue
            # Delete old version, will be re-inserted below
            await db.addins.delete_one({"_id": existing["_id"]})
            logger.debug(f"Refreshing addin '{manifest['id']}' for user {user_id}")

        # Merge config + UI metadata so frontend can read icon/label
        settings = dict(manifest.get("config", {}))
        ui_meta = manifest.get("ui", {})
        if ui_meta.get("icon"):
            settings["icon"] = ui_meta["icon"]
        if ui_meta.get("label"):
            settings["label"] = ui_meta["label"]
        if ui_meta.get("mountPoints"):
            settings["mountPoints"] = ui_meta["mountPoints"]

        # Insert the addin as disabled (user opts in via the UI)
        addin_doc = {
            "userId": user_id,
            "name": manifest["id"],
            "displayName": manifest.get("name", manifest["id"]),
            "description": manifest.get("description", ""),
            "addinType": manifest["type"],
            "enabled": False,
            "config": {"settings": settings},
            "installedAt": datetime.utcnow(),
            "version": manifest.get("version", "1.0.0"),
            "permissions": manifest.get("permissions", []),
            "builtIn": True,
        }
        await db.addins.insert_one(addin_doc)
        seeded += 1
        logger.debug(f"Seeded addin '{manifest['id']}' for user {user_id}")

    if seeded:
        logger.info(f"Seeded {seeded} built-in addins for user {user_id}")
    return seeded


async def seed_built_in_addins(db: Any) -> int:
    """Seed built-in add-ins for all existing users.

    Args:
        db: Database instance (SQLiteDatabase or MongoDB).

    Returns:
        Number of addins seeded across all users.
    """
    user_ids = []
    async for user in db.users.find({}):
        user_ids.append(str(user["_id"]))

    if not user_ids:
        logger.debug("No users found — skipping addin seeding")
        return 0

    total = 0
    for uid in user_ids:
        total += await seed_built_in_addins_for_user(db, uid)
    return total
