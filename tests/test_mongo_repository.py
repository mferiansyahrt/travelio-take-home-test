"""Round trip against a real MongoDB. Runs only when MONGO_TEST_URI is set (the docker compose `tests` service sets it)."""
import os
import uuid

import pytest

pytest.importorskip("pymongo")

from agents.message_classifier_agent import ClassificationOutput
from db_clients import ClassificationRecord
from db_clients.mongo_svc import MongoClassificationRepository
from helpers import FIXED_NOW, SAMPLE_BOOKING_MESSAGE, llm_json

MONGO_TEST_URI = os.getenv("MONGO_TEST_URI")

pytestmark = pytest.mark.skipif(not MONGO_TEST_URI, reason="MONGO_TEST_URI is not set")


async def test_record_with_stay_dates_round_trips_through_mongo():
    repository = MongoClassificationRepository(MONGO_TEST_URI, "travelio_test", f"classifications_{uuid.uuid4().hex[:8]}")
    record = ClassificationRecord(
        id=uuid.uuid4().hex,
        request_id="test-request",
        created_at=FIXED_NOW,
        status="succeeded",
        message=SAMPLE_BOOKING_MESSAGE,
        output=ClassificationOutput.model_validate_json(llm_json()),
        attempts=1,
        latency_ms=12.5,
    )

    try:
        await repository.init_indexes()
        assert await repository.ping() is True

        await repository.save(record)

        assert await repository.get(record.id) == record
        assert await repository.get("missing") is None
    finally:
        await repository._collection.drop()
        await repository.close()


async def test_unrecognized_intent_is_kept_when_read_back_from_mongo():
    repository = MongoClassificationRepository(MONGO_TEST_URI, "travelio_test", f"classifications_{uuid.uuid4().hex[:8]}")
    record = ClassificationRecord(
        id=uuid.uuid4().hex,
        request_id="test-request",
        created_at=FIXED_NOW,
        status="succeeded",
        message="saya mau komplain",
        output=ClassificationOutput.model_validate_json(llm_json(intent="complaint")),
        needs_human_reasons=["unknown_intent"],
        attempts=1,
        latency_ms=8.0,
    )

    try:
        await repository.save(record)

        reloaded = await repository.get(record.id)

        assert reloaded.output.intent.value == "unknown"
        assert reloaded.output.unrecognized_intent == "complaint"
        assert reloaded == record
    finally:
        await repository._collection.drop()
        await repository.close()
