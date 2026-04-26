import json
import logging
from datetime import UTC, datetime

from ..core.redis import get_redis

logger = logging.getLogger(__name__)

_CHANNEL = "todo:events"


async def publish_event(project_id: str, event_type: str, data: dict) -> None:
    try:
        redis = get_redis()
        # ``server_time`` is consumed by clients as the cursor for
        # ``list_tasks(updated_since=...)`` reconcile (S2-3). Always UTC.
        payload = json.dumps({
            "type": event_type,
            "project_id": project_id,
            "data": data,
            "server_time": datetime.now(UTC).isoformat(),
        })
        await redis.publish(_CHANNEL, payload)
    except Exception as e:
        logger.warning("Failed to publish event %s: %s", event_type, e)


async def publish_user_event(
    user_id: str,
    event_type: str,
    data: dict,
    project_id: str | None = None,
) -> None:
    """Publish a user-scoped event.

    The event carries ``user_id`` so the SSE delivery layer can route
    it only to that user's connections (Workbench layout sync etc.).
    ``project_id`` is optional and, when present, also participates in
    project-membership filtering on the receiver side.
    """
    try:
        redis = get_redis()
        message: dict = {
            "type": event_type,
            "user_id": user_id,
            "data": data,
            "server_time": datetime.now(UTC).isoformat(),
        }
        if project_id is not None:
            message["project_id"] = project_id
        await redis.publish(_CHANNEL, json.dumps(message))
    except Exception as e:
        logger.warning("Failed to publish user event %s: %s", event_type, e)
