"""
W7 Stage 2: load the prompt, call the model.
W7 Stage 3: parse the answer, validate it against the schema, repair once
if it failed, and quarantine (never crash, never return raw model text) if
the repair also fails.
W7 Stage 4: a real client timeout, retries with backoff+jitter on the
right failures only, and a structured cost log line per call. The SDK
retries twice on its own by default and times out after ten minutes by
default -- both wrong for an HTTP endpoint, so both are overridden
explicitly below (see README for why).
"""
import json
import logging
import os
import random
import re
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import openai
from openai import OpenAI
from pydantic import ValidationError

from schemas import TriageResponse

PROMPT_PATH = Path(__file__).parent / "prompts" / "triage-v1.md"
PROMPT_VERSION = "triage-v1"
QUARANTINE_PATH = Path(__file__).parent / "logs" / "quarantine.jsonl"

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)

# Retried with backoff: the request either got no useful answer (timeout,
# connection drop) or the server told us to slow down / it's overloaded.
# Never retried: BadRequestError (400, our request is wrong), Authentication
# Error (401, a bad key will still be a bad key in 4 seconds) or
# PermissionDeniedError (403) -- retrying those just burns quota.
RETRYABLE_ERRORS = (
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.RateLimitError,
    openai.InternalServerError,
)
MAX_ATTEMPTS = 3  # one original call + up to two retries
BACKOFF_SECONDS = [1, 2, 4]  # exponential; jitter added on top of each

logger = logging.getLogger("triage.llm")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)


class TriageFailedError(Exception):
    """Raised when the model's answer still doesn't validate after one
    repair attempt."""


@lru_cache(maxsize=1)
def load_prompt() -> str:
    """Cached so the file is only read once per process. A new prompt
    version means a new file (triage-v2.md) and a restart, not an
    in-place edit while the server is running."""
    return PROMPT_PATH.read_text()


def get_client() -> OpenAI:
    """Built lazily, on first real call, so the app can start (and stub
    mode / the kill switch) without LLM_BASE_URL/LLM_API_KEY ever being
    set. max_retries=0 disables the SDK's own default-of-2 retries -- we
    implement our own policy below instead, so it's explicit and logged
    rather than silent."""
    return OpenAI(
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.environ["LLM_API_KEY"],
        timeout=float(os.environ.get("LLM_TIMEOUT", "30.0")),
        max_retries=0,
    )


def _retry_delay(attempt_index: int, exc: Exception) -> float:
    """Obey a Retry-After header if the provider sent one; otherwise
    exponential backoff (1s, 2s, 4s) plus jitter, so many clients retrying
    at once don't all hit the server in the same instant."""
    response = getattr(exc, "response", None)
    header = getattr(response, "headers", {}).get("Retry-After") if response is not None else None
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    base = BACKOFF_SECONDS[min(attempt_index, len(BACKOFF_SECONDS) - 1)]
    return base + random.uniform(0, base * 0.5)


def _log_call(*, model: str, duration_ms: int, repaired: bool, retries: int, ok: bool, **extra) -> None:
    """One structured line per call attempt, to stdout -- Twelve-Factor
    style, so the environment routes it rather than us inventing a log
    file. This is what answers "how much will this cost at scale"."""
    logger.info(json.dumps({
        "event": "llm_call",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "duration_ms": duration_ms,
        "repaired": repaired,
        "retries": retries,
        "ok": ok,
        **extra,
    }))


def _chat(messages: list[dict], *, repaired: bool = False) -> str:
    client = get_client()
    model = os.environ.get("LLM_MODEL", "")
    last_exc = None

    for attempt in range(MAX_ATTEMPTS):
        start = time.monotonic()
        try:
            res = client.chat.completions.create(model=model, temperature=0, messages=messages)
        except RETRYABLE_ERRORS as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            _log_call(
                model=model, duration_ms=duration_ms, repaired=repaired, retries=attempt,
                ok=False, error=type(exc).__name__,
            )
            last_exc = exc
            if attempt + 1 < MAX_ATTEMPTS:
                time.sleep(_retry_delay(attempt, exc))
                continue
            raise
        else:
            duration_ms = int((time.monotonic() - start) * 1000)
            usage = res.usage
            _log_call(
                model=model, duration_ms=duration_ms, repaired=repaired, retries=attempt,
                ok=True,
                input_tokens=getattr(usage, "prompt_tokens", None),
                output_tokens=getattr(usage, "completion_tokens", None),
            )
            return res.choices[0].message.content

    raise last_exc  # unreachable in practice; keeps type checkers happy


def call_model(user_text: str) -> str:
    """Sends the prompt as the system message and the caller's data as a
    separate user message -- never concatenated together."""
    return _chat(
        [
            {"role": "system", "content": load_prompt()},
            {"role": "user", "content": user_text},
        ]
    )


def _extract_json(raw: str) -> dict:
    """Models like to wrap JSON in a code fence, or add "Sure! Here's the
    JSON:" in front. Try the whole string first; if that fails, pull out
    the largest {...} span and try again."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    match = _JSON_OBJECT_RE.search(raw)
    if not match:
        raise ValueError("no JSON object found in the model's response")
    return json.loads(match.group(0))  # lets JSONDecodeError propagate


def _parse_and_validate(raw: str) -> TriageResponse:
    """Raises ValueError (bad JSON) or pydantic.ValidationError (wrong
    shape) on failure -- both are treated the same way by the caller, as
    a single "this needs a repair attempt" case."""
    obj = _extract_json(raw)
    return TriageResponse.model_validate(obj)


def _quarantine(user_text: str, model: str, error: str, raw_output: str) -> None:
    """A separate log for answers that failed validation twice, kept with
    the reason -- set aside for review instead of crashing the request or
    silently reaching a caller."""
    QUARANTINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "input": user_text,
        "error": error,
        "raw_output": raw_output,
    }
    with QUARANTINE_PATH.open("a") as f:
        f.write(json.dumps(record) + "\n")


def call_with_repair(user_text: str) -> TriageResponse:
    """The whole Stage 3+4 loop: call (with its own timeout/retry policy),
    parse+validate, repair once on a schema failure, quarantine and raise
    on a second failure. Never returns raw model text."""
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
        ],
        repaired=True,
    )
    try:
        return _parse_and_validate(repair_raw)
    except (ValueError, ValidationError) as second_error:
        _quarantine(user_text, model, str(second_error), repair_raw)
        raise TriageFailedError(
            "the model's answer did not match the required schema, even after one repair attempt"
        ) from second_error
