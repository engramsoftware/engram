"""
Notification scheduler.

Background task that runs every 30 seconds, checks for due notifications
in MongoDB, and sends them via the email service. Designed to be started
once at app startup and run until shutdown.

Typical usage:
    # In FastAPI lifespan:
    scheduler = NotificationScheduler()
    task = asyncio.create_task(scheduler.run())
    # On shutdown:
    scheduler.stop()
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from notifications.email_service import EmailService, build_notification_html

logger = logging.getLogger(__name__)

# How often to check for due notifications (seconds)
CHECK_INTERVAL = 30

# How many scheduler ticks between graph prune runs (~7 days at 30s intervals)
_GRAPH_PRUNE_INTERVAL_TICKS = (7 * 24 * 60 * 60) // CHECK_INTERVAL

# Daily digest runs once per day (~24h at 30s intervals)
_DIGEST_INTERVAL_TICKS = (24 * 60 * 60) // CHECK_INTERVAL


class NotificationScheduler:
    """Background scheduler that sends due email notifications.

    Polls MongoDB every CHECK_INTERVAL seconds for notifications with
    status='pending' and scheduledAt <= now, then sends them via SMTP.

    Args:
        None — uses the global database connection.
    """

    def __init__(self) -> None:
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._tick_count = 0  # Counts scheduler ticks for periodic tasks

    def start(self) -> None:
        """Start the scheduler as a background task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Notification scheduler started (interval=%ds)", CHECK_INTERVAL)

    def stop(self) -> None:
        """Stop the scheduler gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("Notification scheduler stopped")

    async def _loop(self) -> None:
        """Main scheduler loop — checks for due notifications periodically."""
        while self._running:
            try:
                await self._process_due_notifications()
            except Exception as e:
                logger.error(f"Scheduler error: {e}", exc_info=True)

            # Periodic tasks based on tick count
            self._tick_count += 1

            # Daily digest (~24h)
            if self._tick_count % _DIGEST_INTERVAL_TICKS == 0:
                try:
                    await self._send_daily_digests()
                except Exception as e:
                    logger.error(f"Daily digest error: {e}", exc_info=True)

            # Graph pruning (~weekly)
            if self._tick_count % _GRAPH_PRUNE_INTERVAL_TICKS == 0:
                try:
                    await self._prune_knowledge_graph()
                except Exception as e:
                    logger.error(f"Graph prune error: {e}", exc_info=True)

            await asyncio.sleep(CHECK_INTERVAL)

    async def _process_due_notifications(self) -> None:
        """Find and send all notifications that are due.

        Queries MongoDB for notifications with status='pending' and
        scheduledAt <= now. For each, loads the user's email config,
        sends the email, and updates the notification status.
        """
        from database import get_database
        db = get_database()

        # Use local timezone-aware "now" so comparison with scheduledAt
        # (which is stored in local time) works correctly.
        try:
            from config import get_settings
            _settings = get_settings()
            if _settings.timezone:
                import zoneinfo
                _local_tz = zoneinfo.ZoneInfo(_settings.timezone)
            else:
                _local_tz = datetime.now().astimezone().tzinfo
            now = datetime.now(_local_tz)
        except Exception:
            now = datetime.now().astimezone()

        # Find all pending notifications that are due
        cursor = db.notifications.find({
            "status": "pending",
            "scheduledAt": {"$lte": now},
        })

        count = 0
        async for notif in cursor:
            user_id = notif["userId"]
            subject = notif["subject"]
            body = notif["body"]
            notif_id = notif["_id"]

            # Load user's email settings
            settings = await db.llm_settings.find_one({"userId": user_id})
            if not settings:
                await self._mark_failed(db, notif_id, "No email settings configured")
                continue

            email_cfg = settings.get("email", {})
            if not email_cfg.get("enabled") or not email_cfg.get("username") or not email_cfg.get("password"):
                await self._mark_failed(db, notif_id, "Email not configured or disabled")
                continue

            try:
                from utils.encryption import decrypt_api_key
                smtp_password = decrypt_api_key(email_cfg["password"])
            except Exception:
                await self._mark_failed(db, notif_id, "Failed to decrypt SMTP password")
                continue

            service = EmailService(
                smtp_host=email_cfg.get("smtpHost", "smtp.gmail.com"),
                smtp_port=email_cfg.get("smtpPort", 587),
                username=email_cfg["username"],
                password=smtp_password,
                from_name=email_cfg.get("fromName", "Engram"),
            )
            recipient = email_cfg.get("recipient") or email_cfg["username"]

            # Build HTML version
            html_body = build_notification_html(
                title=subject,
                body=f"<p>{'</p><p>'.join(body.split(chr(10) + chr(10)))}</p>",
            )

            success = await service.send(
                to=recipient,
                subject=f"Engram — {subject}",
                body=body,
                html_body=html_body,
            )

            if success:
                await db.notifications.update_one(
                    {"_id": notif_id},
                    {"$set": {"status": "sent", "sentAt": datetime.utcnow()}},
                )
                count += 1
                logger.info(
                    f"Scheduler sent notification '{subject}' to {recipient} "
                    f"(user={user_id})"
                )
            else:
                await self._mark_failed(db, notif_id, "SMTP send failed")

        if count > 0:
            logger.info(f"Scheduler processed {count} due notification(s)")

    @staticmethod
    async def _mark_failed(db, notif_id, error: str) -> None:
        """Mark a notification as failed with an error message.

        Args:
            db: MongoDB database instance.
            notif_id: The notification's ObjectId.
            error: Human-readable error description.
        """
        await db.notifications.update_one(
            {"_id": notif_id},
            {"$set": {"status": "failed", "error": error}},
        )
        logger.warning(f"Notification {notif_id} failed: {error}")


    async def _send_daily_digests(self) -> None:
        """Generate and store daily digests for all users.

        Creates a digest notification in the database. If email is configured,
        it will be picked up by the normal notification flow. The digest is
        also retrievable via the /digest slash command.
        """
        from database import get_database
        from notifications.daily_digest import generate_daily_digest

        db = get_database()

        # Get all user IDs
        user_ids = await db.users.distinct("_id")

        for uid in user_ids:
            try:
                digest = await generate_daily_digest(user_id=str(uid))
                if not digest.get("summary") or digest.get("total_messages", 0) == 0:
                    continue

                # Store as a notification so email flow picks it up
                await db.notifications.insert_one({
                    "userId": str(uid),
                    "subject": "Daily Digest",
                    "body": digest["summary"],
                    "status": "pending",
                    "scheduledAt": datetime.utcnow(),
                    "createdAt": datetime.utcnow(),
                    "metadata": {"type": "daily_digest"},
                })
                logger.info(
                    f"Daily digest generated for user {uid}: "
                    f"{len(digest.get('conversations', []))} conversations"
                )
            except Exception as e:
                logger.warning(f"Daily digest failed for user {uid}: {e}")

    async def _prune_knowledge_graph(self) -> None:
        """Run periodic cleanup on the Neo4j knowledge graph.

        Removes orphaned nodes older than 90 days and retroactively
        invalid entities. Runs for each user that has graph data.
        """
        from database import get_database
        from config import get_settings

        settings = get_settings()
        if not settings.neo4j_uri or not settings.neo4j_password:
            return

        try:
            from knowledge_graph.graph_store import get_graph_store
            graph_store = get_graph_store(
                uri=settings.neo4j_uri,
                username=settings.neo4j_username,
                password=settings.neo4j_password,
                database=settings.neo4j_database,
            )
            if not graph_store or not graph_store.is_available:
                return

            # Get all user IDs that have graph data
            db = get_database()
            user_ids = await db.users.distinct("_id")

            for uid in user_ids:
                stats = graph_store.prune_stale_nodes(str(uid), max_age_days=90)
                if stats["orphaned_removed"] > 0 or stats["invalid_removed"] > 0:
                    logger.info(f"Graph pruned for user {uid}: {stats}")

        except Exception as e:
            logger.warning(f"Knowledge graph prune skipped: {e}")


# Singleton instance — started in main.py lifespan
notification_scheduler = NotificationScheduler()
