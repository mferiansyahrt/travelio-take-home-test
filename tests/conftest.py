import pytest
from httpx import ASGITransport, AsyncClient

from db_clients import InMemoryApiRequestLogRepository, InMemoryClassificationRepository
from helpers import FIXED_NOW, ScriptedLLMClient, build_agent
from main_processor import MainProcessor
from services.swagger_service import app, get_processor


@pytest.fixture
def repository():
    return InMemoryClassificationRepository()


@pytest.fixture
def request_log():
    return InMemoryApiRequestLogRepository()


@pytest.fixture
async def make_client(repository, request_log):
    """Factory for an HTTP client on the real FastAPI app, wired to a scripted LLM and the in-memory repository.

    Usage: `client, llm = make_client([llm_json()], max_retries=0)`
    """
    clients: list[AsyncClient] = []
    # The lifespan doesn't run under ASGITransport, so the request log is attached here.
    app.state.request_log = request_log

    def factory(script: list, **agent_overrides):
        llm_client = ScriptedLLMClient(script)
        processor = MainProcessor(
            build_agent(llm_client, **agent_overrides),
            repository,
            timezone_name="Asia/Jakarta",
            now_fn=lambda: FIXED_NOW,
        )
        app.dependency_overrides[get_processor] = lambda: processor
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
        clients.append(client)
        return client, llm_client

    yield factory

    app.dependency_overrides.clear()
    del app.state.request_log
    for client in clients:
        await client.aclose()
