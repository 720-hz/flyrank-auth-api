"""
W7 Stage 2: load the prompt, call the model.
"""
import os
from functools import lru_cache
from pathlib import Path

from openai import OpenAI

PROMPT_PATH = Path(__file__).parent / "prompts" / "triage-v1.md"
PROMPT_VERSION = "triage-v1"


@lru_cache(maxsize=1)
def load_prompt() -> str:
    return PROMPT_PATH.read_text()


def get_client() -> OpenAI:
    return OpenAI(
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.environ["LLM_API_KEY"],
    )


def call_model(user_text: str) -> str:
    client = get_client()
    model = os.environ.get("LLM_MODEL", "")
    res = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[
            {"role": "system", "content": load_prompt()},
            {"role": "user", "content": user_text},
        ],
    )
    return res.choices[0].message.content
