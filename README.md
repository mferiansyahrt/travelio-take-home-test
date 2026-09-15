# Travelio AI Developer Test

| Part | Where |
|---|---|
| A: Prompt engineering & structured extraction | [`docs/part_a_prompt_engineering.md`](docs/part_a_prompt_engineering.md) |
| B: LLM pipeline as a FastAPI service | this README, code in [`source/`](source/), tests in [`tests/`](tests/) |
| C: Databases & data debugging | [`part_c/part_c_databases.pdf`](part_c/part_c_databases.pdf), queries in [`part_c/`](part_c/) |
| D: Eval & observability | [`part_d/part_d_eval_and_observability.pdf`](part_d/part_d_eval_and_observability.pdf) |
| E: Dagster pipeline design | [`part_e/part_e_dagster_pipeline.pdf`](part_e/part_e_dagster_pipeline.pdf) |

---

# Part B: Guest Message Classifier service

A FastAPI endpoint that runs the Part A prompt through the LLM, validates and retries the answer, applies guardrails, and persists every result to MongoDB (or an in-memory repository).

The LLM is the provided `MockLLMClient`, copied **unchanged** to [`source/llm_clients/mock_llm.py`](source/llm_clients/mock_llm.py). No real API is called.

> **Intents in API responses are random. This comes from the provided mock, not from the service.**
> `MockLLMClient.complete()` never reads the prompt: it picks `intent`, `urgency` and `confidence` at random and always returns empty entities, so the same message sent twice gets different intents. (Checked: 40 calls with an *empty* prompt give the same random mix as 40 calls with the booking message.)
> What the running service demonstrates is the pipeline: prompt construction, timeout and retry, strict validation, guardrails, persistence and status codes. Classification behaviour is covered by the Part A prompt and by the tests, which use a scripted LLM with a fixed answer; with a fixed answer the same request returns an identical result every time.

## Run it

```bash
pip install -r requirements-dev.txt                        # Python 3.11
pytest                                                     # MongoDB integration test is skipped unless MONGO_TEST_URI is set
cd source && python -m services.run_swagger_service -p 8000   # in-memory repository by default
# Swagger UI: http://localhost:8000/docs
```

With Docker (API + MongoDB): `docker compose up -d --build --wait api`. Tests in a clean container: `docker compose --profile test run --rm tests`. On CPUs without AVX, MongoDB 5+ won't start; prefix the commands with `MONGO_IMAGE=mongo:4.4`.

## API

### `POST /classify-message`

```bash
curl -s -X POST localhost:8000/classify-message \
  -H 'Content-Type: application/json' -H 'X-Request-ID: demo-1' \
  -d '{"message": "Halo, saya mau booking unit 2BR di Kemang dari tgl 12 sampai 15 Maret, masih ada yg available?"}'
```

`200 OK`, an actual response from the service running the provided mock:

```json
{
  "id": "d251a493a3914f9c8ebc03d1592ec476",
  "request_id": "demo-1",
  "intent": "extension_request",
  "entities": {"stays": []},
  "urgency": "low",
  "confidence": 0.62,
  "needs_human": false,
  "needs_human_reasons": [],
  "reason": null,
  "unrecognized_intent": null,
  "attempts": 1,
  "latency_ms": 280.3,
  "persisted": true,
  "created_at": "2026-09-15T13:03:03.810000Z"
}
```

The intent is wrong for this message and the entities are empty, because the mock picked `extension_request` at random. The answer a real model should give with this prompt is in [Part A §3](docs/part_a_prompt_engineering.md#3-expected-output-for-the-sample-inbox): `booking_inquiry` with `stays: [{"location": "Kemang", "unit_type": "2br", "check_in": "2027-03-12", "check_out": "2027-03-15"}]`.

| Status | When | Body |
|---|---|---|
| `200` | Classified, including `intent: unknown`. Check `needs_human` / `needs_human_reasons`. | classification |
| `422` | Invalid body: empty or whitespace-only message, message over 2000 chars, bad context role | FastAPI validation detail |
| `502` | The LLM kept returning invalid output on every attempt | `{"error": {"code": "llm_malformed_output", ...}, "request_id", "id", "attempts", "persisted", "needs_human": true}` |
| `504` | The LLM timed out on every attempt | same shape, `code: "llm_timeout"` |
| `500` | Unexpected error (logged with stack trace) | `code: "internal_error"` |

Every response carries `X-Request-ID`. Also available: `GET /classifications/{id}` (the stored record) and `GET /health`.

## How a request flows

```
HTTP ─► middleware (request_id, access log)
     ─► MainProcessor.process()                                   source/main_processor.py
          ─► MessageClassifierAgent.run()                          source/agents/message_classifier_agent/
               build prompt (reference datetime Asia/Jakarta, escaped guest text, last N context turns)
               BaseAgent._complete_with_retry()                    source/agents/base.py
                 asyncio.wait_for(llm.complete(), LLM_TIMEOUT_SECONDS)
                 strict Pydantic validation ── invalid/timeout ─► backoff, retry (1 + LLM_MAX_RETRIES attempts)
               guardrails → final needs_human + reasons
          ─► repository.save(record)  (success AND failure; best effort)   source/db_clients/
     ─► 200 | 502 | 504
```

## Project structure

```
source/
├── agents/
│   ├── base.py                          # BaseAgent: timeout + retry policy, LLMFailure / LLMOutputError
│   └── message_classifier_agent/
│       ├── agent.py                     # prompt building, output parsing, run()
│       ├── prompt.py                    # SYSTEM (role/task/context/output format/examples) + HUMAN prompt
│       ├── schema.py                    # Pydantic output contract (Intent, Stay, Entities, ClassificationOutput)
│       └── guardrails.py                # service-side needs_human rules + injection patterns
├── config/__init__.py                   # pydantic-settings, env-overridable
├── db_clients/                          # ClassificationRepository protocol, memory_svc.py, mongo_svc.py
├── llm_clients/                         # LLMClient protocol + provided mock (unchanged)
├── services/                            # swagger_service.py (FastAPI app), run_swagger_service.py (uvicorn runner)
├── utils/                               # logger.py (JSON logs), clean_json.py (code-fence strip, no repair)
└── main_processor.py                    # orchestration: agent → timing → persistence
tests/                                   # endpoint, agent/guardrail/prompt unit tests, MongoDB integration test
docs/                                    # Part A write-up, generated JSON Schema + rendered prompt
part_c/ part_d/ part_e/                  # Parts C, D, E (PDF) + C queries
```

## Key design decisions

1. **Retry budget sized from the mock's failure rates.** About 12% of attempts fail (8% malformed + 4% timeout). With 3 attempts (`LLM_MAX_RETRIES=2`) roughly 0.17% of requests still fail. Measured with 300 requests: 266 succeeded on attempt 1, 32 on attempt 2, 2 on attempt 3, no errors. With retries disabled, 17 of 200 requests (8.5%) failed: 10 with 502 and 7 with 504.
2. **The agent enforces its own timeout.** The mock ignores its `timeout` argument, so every call is wrapped in `asyncio.wait_for`.
3. **Strict validation, no JSON repair.** Repairing the mock's truncated JSON would hide malformed output and accept half an answer; invalid output fails validation and is retried.
4. **An unknown intent is not a malformed answer.** An intent outside the enum is mapped to `unknown`, kept in `unrecognized_intent`, and escalated, with no retry.
5. **502 vs 504.** `504` only when every attempt timed out, otherwise `502`. Error bodies still say `needs_human: true`.
6. **`needs_human` is decided by the service**, because the mock always says `false`. The rules are unknown intent, confidence < 0.6, high urgency, an injection pattern, or the model's own flag. They only escalate.
7. **Prompt-injection defence in depth.** Delimited and escaped guest text, an explicit instruction, and a regex guardrail.
8. **Everything is persisted, including failures**, best effort (`persisted: false` if the database is down).
9. **Injectable boundaries.** `LLMClient` and `ClassificationRepository` are protocols; tests override FastAPI's `get_processor` with a scripted LLM and the in-memory repository.
10. **MongoDB through PyMongo's async client**, with indexes on `created_at`, `request_id` and `(output.intent, created_at)`.
11. **Structured JSON logs** with `request_id` on every line. Guest text is never logged.

## Assumptions

- Timezone is Asia/Jakarta. A day and month without a year means the next occurrence that isn't in the past.
- One routable intent per message; the most urgent request wins.
- `urgency` is top-level (a property of the message, as in the mock).
- Internal service: no API auth. Local MongoDB has no auth and is bound to localhost.

## What I'd do with more time

- A real LLM client with structured-output mode, provider fallback, a circuit breaker and an overall request deadline.
- A labelled eval set and harness, and `prompt_version` stored on every record (see Part D).
- Prometheus metrics and alerts for attempts, invalid output, timeouts, needs-human rate and latency.
- `secondary_intents`, location normalisation, rejecting past booking dates.
- Idempotency keys, API auth and rate limiting, TTL / PII redaction on stored messages, MongoDB auth and TLS.
