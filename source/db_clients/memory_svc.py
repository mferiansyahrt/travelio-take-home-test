from .base import ApiRequestLog, ClassificationRecord


class InMemoryClassificationRepository:
    """Process-local store for tests and quick local runs. Data is lost on restart and not shared between workers."""

    def __init__(self):
        self._records: dict[str, ClassificationRecord] = {}

    async def save(self, record: ClassificationRecord) -> None:
        # Copies on the way in and out, so callers can't mutate stored state (same semantics as a real DB).
        self._records[record.id] = record.model_copy(deep=True)

    async def get(self, record_id: str) -> ClassificationRecord | None:
        record = self._records.get(record_id)
        return record.model_copy(deep=True) if record else None

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None

    def __len__(self) -> int:
        return len(self._records)


class InMemoryApiRequestLogRepository:
    """Request log kept in a list, for tests and in-memory runs."""

    def __init__(self):
        self.logs: list[ApiRequestLog] = []

    async def save(self, log: ApiRequestLog) -> None:
        self.logs.append(log.model_copy(deep=True))

    async def close(self) -> None:
        return None
