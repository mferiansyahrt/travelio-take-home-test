from helpers import SAMPLE_BOOKING_MESSAGE, TRUNCATED_MOCK_OUTPUT, llm_json


async def test_every_call_is_logged_with_its_request_and_response_body(make_client, request_log):
    client, _ = make_client([llm_json(), TRUNCATED_MOCK_OUTPUT], max_retries=0)

    ok = await client.post("/classify-message", json={"message": SAMPLE_BOOKING_MESSAGE})
    failed = await client.post("/classify-message", json={"message": "halo"})
    invalid = await client.post("/classify-message", json={"message": "   "})
    missing = await client.get("/no-such-route?x=1")

    assert [log.status_code for log in request_log.logs] == [200, 502, 422, 404]
    first, second, third, fourth = request_log.logs

    assert first.method == "POST" and first.path == "/classify-message"
    assert first.request_body == {"message": SAMPLE_BOOKING_MESSAGE}
    assert first.response_body == ok.json()
    assert first.request_id == ok.headers["X-Request-ID"]

    assert second.response_body["error"]["code"] == "llm_malformed_output"
    assert third.response_body == invalid.json()
    assert fourth.query == "x=1" and fourth.response_body == missing.json()
    assert failed.status_code == 502


async def test_documentation_pages_and_the_docker_healthcheck_are_not_logged(make_client, request_log):
    client, _ = make_client([])

    await client.get("/openapi.json")
    await client.get("/docs")
    await client.get("/health", headers={"User-Agent": "docker-healthcheck"})
    health = await client.get("/health")

    assert [log.path for log in request_log.logs] == ["/health"]
    assert request_log.logs[0].response_body == health.json()
