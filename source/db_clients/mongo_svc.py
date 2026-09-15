from loguru import logger
from pymongo import ASCENDING, DESCENDING, AsyncMongoClient
from pymongo.errors import PyMongoError

from .base import ClassificationRecord


class MongoClassificationRepository:
    """Stores classification records in MongoDB, one document per /classify-message call.

    Uses PyMongo's native async client (Motor is deprecated in favour of it).
    """

    def __init__(self, uri: str, db_name: str, collection_name: str, server_selection_timeout_ms: int = 3000):
        self._client = AsyncMongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=server_selection_timeout_ms)
        self._collection = self._client[db_name][collection_name]

    async def init_indexes(self) -> None:
        """Create indexes at startup. Idempotent: existing indexes are left as they are."""
        await self._collection.create_index([("created_at", DESCENDING)])
        await self._collection.create_index([("request_id", ASCENDING)])
        # For "messages per intent per day" reporting and needs-human dashboards.
        await self._collection.create_index([("output.intent", ASCENDING), ("created_at", DESCENDING)])

    async def save(self, record: ClassificationRecord) -> None:
        # mode="json" turns `date` values (check-in/out) into ISO strings, because BSON has no date-only type.
        # created_at is put back as a real datetime so range queries and TTL indexes work on it.
        document = record.model_dump(mode="json")
        document["_id"] = document.pop("id")
        document["created_at"] = record.created_at
        await self._collection.insert_one(document)

    async def get(self, record_id: str) -> ClassificationRecord | None:
        document = await self._collection.find_one({"_id": record_id})
        if document is None:
            return None
        document["id"] = document.pop("_id")
        return ClassificationRecord.model_validate(document)

    async def ping(self) -> bool:
        try:
            await self._client.admin.command("ping")
            return True
        except PyMongoError as exc:
            logger.bind(error=str(exc)).warning("mongo_ping_failed")
            return False

    async def close(self) -> None:
        await self._client.close()
