"""
W7 Stage 2: load the prompt, call the model.
W7 Stage 3: parse the answer, validate it against the schema, repair once
if it failed, and quarantine (never crash, never return raw model text) if
the repair also fails.
"""
import json
import os
import re
from functools import lru_cache
from pathlib import Path

from openai import OpenAI
from pydantic import ValidationError

from schemas import TriageResponse

PROMPT_PATH = Path(__file__).parent / "prompts" / "triage-v1.md"
PROMPT_VERSION = "triage-v1"
QUARANTINE_PATH = Path(__file__).parent / "logs" / "quarantine.jsonl"

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


class TriageFailedError(Exception):
    """Raised when the model's answer still doesn't validate after one
    repair attempt."""


@lru_cache(maxsize=1)
def load_prompt() -> str:
    return PROMPT_PATH.read_text()


def get_client() -> OpenAI:
    return OpenAI(
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.environ["LLM_API_KEY"],
    )


def _chat(messages: list[dict]) -> str:
    client = get_client()
    model = os.environ.get("LLM_MODEL", "")
    res = client.chat.completions.create(model=model, temperature=0, messages=messages)
    return res.choices[0].message.content


def call_model(user_text: str) -> str:
    return _chat(
        [
            {"role": "system", "content": load_prompt()},
            {"role": "user", "content": user_text},
        ]
    )


def _extract_json(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    match = _JSON_OBJECT_RE.search(raw)
    if not match:
        raise ValueError("no JSON object found in the model's response")
    return json.loads(match.group(0))  # lets JSONDecodeError propagate


def _parse_and_validate(raw: str) -> TriageResponse:
    obj = _extract_json(raw)
    return TriageResponse.model_validate(obj)


def _quarantine(user_text: str, model: str, error: str, raw_output: str) -> None:
    QUARANTINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "input": user_text,
        "error": error,
        "raw_output": raw_output,
    }
    with QUARANTINE_PATH.open("a") as f:
        f.write(json.dumps(record) + "\n")


def call_with_repair(user_text: str) -> TriageResponse:
    system = load_prompt()
    model = os.environ.get("LLM_MODEL", "")

    first_raw = _chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ]
    )
    try:
        return _parse_and_validate(first_raw)
    except (ValueError, ValidationError) as exc:
        first_error = exc  # `except ... as name` unbinds name after the block

    repair_raw = _chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": first_raw},
            {
                "role": "user",
                "content": (
                    f"Your previous answer was rejected for this reason: "
                    f"{first_error}. Return only corrected JSON matching the schema."
                ),
            },
        ]
    )
    try:
        return _parse_and_validate(repair_raw)
    except (ValueError, ValidationError) as second_error:
        _quarantine(user_text, model, str(second_error), repair_raw)
        raise TriageFailedError(
            "the model's answer did not match the required schema, even after one repair attempt"
        ) from second_error
