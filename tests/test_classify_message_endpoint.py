import asyncio

from helpers import SAMPLE_BOOKING_MESSAGE, TRUNCATED_MOCK_OUTPUT, llm_json
from services.swagger_service import app, get_processor


# ── Happy path ────────────────────────────────────────────────────────────
async def test_happy_path_returns_classification_and_persists_it(make_client, repository):
    client, llm = make_client([llm_json()])

    response = await client.post("/classify-message", json={"message": SAMPLE_BOOKING_MESSAGE})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "booking_inquiry"
    assert body["entities"]["stays"] == [
        {"location": "Kemang", "unit_type": "2br", "check_in": "2027-03-12", "check_out": "2027-03-15", "new_check_out": None}
    ]
    assert body["needs_human"] is False
    assert body["needs_human_reasons"] == []
    assert body["attempts"] == 1
    assert body["persisted"] is True
    assert response.headers["X-Request-ID"] == body["request_id"]
    assert "2026-09-15T10:00+07:00 (Tuesday, Asia/Jakarta)" in llm.prompts[0]

    stored = await client.get(f"/classifications/{body['id']}")
    assert stored.status_code == 200
    assert stored.json()["status"] == "succeeded"
    assert stored.json()["message"] == SAMPLE_BOOKING_MESSAGE
    assert stored.json()["output"]["intent"] == "booking_inquiry"
    assert len(repository) == 1


async def test_malformed_output_is_retried_then_succeeds(make_client):
    client, llm = make_client([TRUNCATED_MOCK_OUTPUT, llm_json()])

    response = await client.post("/classify-message", json={"message": SAMPLE_BOOKING_MESSAGE})

    assert response.status_code == 200
    assert response.json()["attempts"] == 2
    assert len(llm.prompts) == 2


# ── Failure paths ─────────────────────────────────────────────────────────
async def test_timeout_on_every_attempt_returns_504_and_persists_failure(make_client, repository):
    client, llm = make_client([asyncio.TimeoutError("LLM timed out")] * 3, max_retries=2)

    response = await client.post("/classify-message", json={"message": SAMPLE_BOOKING_MESSAGE})

    assert response.status_code == 504
    body = response.json()
    assert body["error"]["code"] == "llm_timeout"
    assert body["attempts"] == 3
    assert body["needs_human"] is True
    assert len(llm.prompts) == 3

    stored = await repository.get(body["id"])
    assert stored.status == "failed"
    assert stored.attempt_errors == ["timeout", "timeout", "timeout"]


async def test_hanging_llm_is_cut_off_by_the_agent_timeout(make_client):
    # The client sleeps 5s and ignores its timeout argument, like the provided mock would.
    client, _ = make_client([5.0], max_retries=0, timeout_seconds=0.05)

    response = await client.post("/classify-message", json={"message": SAMPLE_BOOKING_MESSAGE})

    assert response.status_code == 504


async def test_persistently_malformed_output_returns_502(make_client):
    client, _ = make_client([TRUNCATED_MOCK_OUTPUT] * 3, max_retries=2)

    response = await client.post("/classify-message", json={"message": SAMPLE_BOOKING_MESSAGE})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "llm_malformed_output"
    assert response.json()["persisted"] is True


async def test_intent_outside_enum_is_mapped_to_unknown_and_escalated(make_client):
    client, llm = make_client([llm_json(intent="complaint")])

    response = await client.post("/classify-message", json={"message": "saya mau komplain"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "unknown"
    assert body["unrecognized_intent"] == "complaint"
    assert body["needs_human"] is True
    assert "unknown_intent" in body["needs_human_reasons"]
    assert len(llm.prompts) == 1  # a valid-but-unroutable answer is not retried


async def test_invalid_request_returns_structured_422_without_calling_the_llm(make_client):
    client, llm = make_client([])

    response = await client.post("/classify-message", json={"message": "   "}, headers={"X-Request-ID": "bad-input-1"})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "invalid_request"
    assert body["error"]["fields"] == [
        {"location": "body.message", "message": "String should have at least 1 character"}
    ]
    assert body["request_id"] == "bad-input-1"
    assert "detail" not in body
    assert "needs_human" not in body
    assert llm.prompts == []


async def test_body_that_is_not_json_returns_structured_422(make_client):
    client, llm = make_client([])

    response = await client.post(
        "/classify-message", content="not json", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert llm.prompts == []


async def test_database_outage_does_not_fail_the_request(make_client, repository, monkeypatch):
    async def broken_save(record):
        raise ConnectionError("database is down")

    monkeypatch.setattr(repository, "save", broken_save)
    client, _ = make_client([llm_json()])

    response = await client.post("/classify-message", json={"message": SAMPLE_BOOKING_MESSAGE})

    assert response.status_code == 200
    assert response.json()["persisted"] is False


async def test_unknown_record_returns_404(make_client):
    client, _ = make_client([])

    response = await client.get("/classifications/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert "needs_human" not in response.json()


async def test_unknown_route_and_wrong_method_use_the_same_error_shape(make_client):
    client, _ = make_client([])

    not_found = await client.get("/no-such-route")
    wrong_method = await client.get("/classify-message")

    assert not_found.status_code == 404
    assert not_found.json()["error"]["code"] == "not_found"
    assert wrong_method.status_code == 405
    assert wrong_method.json()["error"]["code"] == "method_not_allowed"
    assert wrong_method.headers["allow"] == "POST"


async def test_unexpected_error_returns_structured_500(make_client):
    class BrokenProcessor:
        async def process(self, **kwargs):
            raise RuntimeError("boom")

    client, _ = make_client([])
    app.dependency_overrides[get_processor] = lambda: BrokenProcessor()

    response = await client.post("/classify-message", json={"message": "halo"})

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert "needs_human" not in body
    assert response.headers["X-Request-ID"] == body["request_id"]
