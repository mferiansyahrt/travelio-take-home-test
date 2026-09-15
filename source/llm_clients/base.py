from typing import Protocol


class LLMClient(Protocol):
    """Minimal async LLM interface.

    The provided `MockLLMClient` satisfies it, and so do the scripted fakes used in tests,
    which is what lets the agent be tested deterministically.
    """

    async def complete(self, prompt: str, *, timeout: float = 5.0) -> str: ...
