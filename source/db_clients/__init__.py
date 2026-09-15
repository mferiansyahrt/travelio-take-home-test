from .base import ClassificationRecord, ClassificationRepository
from .memory_svc import InMemoryClassificationRepository

__all__ = [
    "ClassificationRecord",
    "ClassificationRepository",
    "InMemoryClassificationRepository",
    "build_repository",
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
