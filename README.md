# Travelio AI Developer Test

| Part | Where |
|---|---|
| A. Prompt engineering & structured extraction | [`docs/part_a/`](docs/part_a/): write-up, JSON schema, rendered prompt |
| B. LLM pipeline as a FastAPI service | this README, [`source/`](source/), [`tests/`](tests/) |
| C. Databases & data debugging | [`docs/part_c/`](docs/part_c/): PDF + C1, C2, C4 queries |
| D. Eval & observability | [`docs/part_d/`](docs/part_d/) (PDF) |
| E. Dagster pipeline design | [`docs/part_e/`](docs/part_e/) (PDF) |

## Part B: `POST /classify-message`

The service runs the Part A prompt through the provided `MockLLMClient` (copied unchanged to [`source/llm_clients/mock_llm.py`](source/llm_clients/mock_llm.py)). It validates the answer with Pydantic, retries on timeouts and invalid output, applies guardrails, and stores every result.

> **The mock ignores the prompt and returns a random intent**, so the same message gets a different intent on each call. The running service demonstrates the pipeline. Classification behaviour is covered by the prompt (Part A) and by tests that use a scripted LLM with fixed answers.

### Run

```bash
pip install -r requirements-dev.txt                          # Python 3.11
pytest -v                                                    # MongoDB test is skipped unless MONGO_TEST_URI is set
cd source && python -m services.run_swagger_service -p 8000  # Swagger UI: http://localhost:8000/docs
```

Settings are environment variables (see [`.env.example`](.env.example)): `LLM_MAX_RETRIES` (default 2), `LLM_TIMEOUT_SECONDS` (5), `CONFIDENCE_THRESHOLD` (0.6), `REPOSITORY_BACKEND` (`memory` or `mongo`), `MONGO_URI`, `LOG_JSON`. With Docker (API + MongoDB): `docker compose up -d --build --wait api`.

### Request and responses

Request: `{"message": "...", "conversation_context": [{"role": "guest" | "agent", "text": "..."}]}`. The context is optional.

| Status | When | Body |
|---|---|---|
| `200` | Classified | `intent`, `entities.stays[]`, `urgency`, `confidence`, `needs_human`, `needs_human_reasons`, `attempts`, `latency_ms`, `persisted`, `id`, `request_id` |
| `422` | Invalid request | `{"error": {"code": "invalid_request", "message", "fields": [{"location", "message"}]}, "request_id"}` |
| `502` | LLM returned invalid output on every attempt | `{"error": {"code": "llm_malformed_output", "message"}, "request_id", "id", "attempts", "persisted", "needs_human": true}` |
| `504` | LLM timed out on every attempt | same as 502, with `code: "llm_timeout"` |
| `404` / `405` / `500` | Unknown record or route / wrong method / unexpected error | same `error` shape (`not_found`, `method_not_allowed`, `internal_error`) |

`GET /classifications/{id}` returns the stored record (input, parsed output, attempts, latency, timestamp). `GET /health` checks the repository. Every response carries an `X-Request-ID` header.

### Key design decisions

- **Retries:** about 12% of mock calls fail (8% malformed, 4% timeout). Three attempts leave about 0.17% of requests failing. In a 300-request run, 266 succeeded on attempt 1, 32 on attempt 2, 2 on attempt 3, with no errors.
- **The agent enforces its own timeout.** The mock ignores `timeout`, so every call is wrapped in `asyncio.wait_for`.
- **Strict validation, no JSON repair.** Truncated JSON must fail and be retried, not be "fixed" into half an answer.
- **Unknown intent is not malformed output.** An intent outside the enum becomes `unknown`, the original value is kept in `unrecognized_intent`, and the message is escalated without a retry.
- **502 vs 504.** `504` only if every attempt timed out; otherwise `502`.
- **`needs_human` is decided by the service**, not trusted from the model. It is set on unknown intent, confidence < 0.6, high urgency, an injection pattern, or the model's own flag. The rules only escalate.
- **Prompt injection:** guest text is delimited and escaped, and a regex guardrail escalates obvious attempts.
- **Persistence:** successes and failures go through a `ClassificationRepository` protocol (in-memory or MongoDB). A database outage still returns the result, with `persisted: false`.
- **Request log:** every HTTP call (any path or status) is also stored in a separate `api_requests` collection with its request and response body, so the API's traffic can be audited from MongoDB. Swagger pages and the Docker healthcheck are skipped.
- **Structured logs:** one JSON line per event (LLM attempt, retry, classification, HTTP request), each with `request_id`. Guest text is never logged.
- **Tests** swap in a scripted LLM, so the happy path and the failure paths are deterministic. Failure paths covered: timeouts (504), malformed output (502), a hanging LLM, unknown intent, database outage, invalid input.

### Assumptions

- Dates are resolved in Asia/Jakarta time. A day and month without a year means the next future occurrence.
- One routable intent per message. If a message has several requests, the most urgent one wins.
- `urgency` is a top-level field, as in the mock's output, not part of `entities`.
- This is an internal service: no API auth. Local MongoDB runs without auth.

### With more time

- A real LLM client with structured-output mode, provider fallback, a circuit breaker and a request-level deadline.
- A labelled eval set, and `prompt_version` stored on every record (see Part D).
- Metrics and alerts for retry, timeout and needs-human rates, and latency.
- `secondary_intents` for multi-request messages, location normalisation, rejecting past booking dates.
- Idempotency keys, API auth, rate limiting, and a retention policy for stored guest messages.
