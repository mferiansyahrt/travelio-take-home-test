from .base import ApiRequestLog, ApiRequestLogRepository, ClassificationRecord, ClassificationRepository
from .memory_svc import InMemoryApiRequestLogRepository, InMemoryClassificationRepository

__all__ = [
    "ApiRequestLog",
    "ApiRequestLogRepository",
    "ClassificationRecord",
    "ClassificationRepository",
    "InMemoryApiRequestLogRepository",
    "InMemoryClassificationRepository",
    "build_repository",
    "build_request_log",
]


async def build_repository(
    backend: str, *, mongo_uri: str, mongo_db_name: str, mongo_collection: str
) -> ClassificationRepository:
    """Create the repository for the configured backend.

    pymongo is imported only for the mongo backend, so unit tests and in-memory runs don't need it.
    """
    if backend == "mongo":
        from .mongo_svc import MongoClassificationRepository

        repository = MongoClassificationRepository(mongo_uri, mongo_db_name, mongo_collection)
        await repository.init_indexes()
        return repository
    return InMemoryClassificationRepository()


async def build_request_log(
    backend: str, *, mongo_uri: str, mongo_db_name: str, mongo_collection: str
) -> ApiRequestLogRepository:
    """Create the HTTP request log store for the configured backend (same backend as the classification records)."""
    if backend == "mongo":
        from .mongo_svc import MongoApiRequestLogRepository

        request_log = MongoApiRequestLogRepository(mongo_uri, mongo_db_name, mongo_collection)
        await request_log.init_indexes()
        return request_log
    return InMemoryApiRequestLogRepository()
