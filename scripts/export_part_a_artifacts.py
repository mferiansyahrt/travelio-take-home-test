"""Regenerate the Part A artifacts from the code, so the docs never drift from what the service actually runs:

- docs/output_schema.json   JSON Schema of the classifier output (from the Pydantic model)
- docs/prompt_example.txt   the full prompt sent to the LLM for sample message 1

Usage (from the repo root):  python scripts/export_part_a_artifacts.py
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source"))

from agents.message_classifier_agent import ClassificationOutput, MessageClassifierAgent  # noqa: E402
from llm_clients import MockLLMClient  # noqa: E402

SAMPLE_MESSAGE = "Halo, saya mau booking unit 2BR di Kemang dari tgl 12 sampai 15 Maret, masih ada yg available?"
REFERENCE_TIME = datetime(2026, 9, 15, 10, 0, tzinfo=ZoneInfo("Asia/Jakarta"))


def main() -> None:
    docs_dir = ROOT / "docs"
    docs_dir.mkdir(exist_ok=True)

    schema_path = docs_dir / "output_schema.json"
    schema_path.write_text(json.dumps(ClassificationOutput.model_json_schema(), indent=2) + "\n")

    agent = MessageClassifierAgent(
        MockLLMClient(),
        timeout_seconds=5.0,
        max_retries=2,
        retry_backoff_seconds=0.2,
        confidence_threshold=0.6,
        max_context_messages=10,
    )
    prompt_path = docs_dir / "prompt_example.txt"
    prompt_path.write_text(agent.build_prompt(SAMPLE_MESSAGE, [], REFERENCE_TIME) + "\n")

    print(f"wrote {schema_path.relative_to(ROOT)} and {prompt_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
