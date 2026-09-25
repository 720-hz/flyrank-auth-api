"""
Stage 0 throwaway check: proves the LLM client is wired up correctly before
any endpoint code exists. Not part of the app -- delete this file once it
has printed "ready" for you.

Run with:
    python -m dotenv run -- python scripts/llm_hello.py
or just make sure the LLM_* vars in .env are exported into your shell first.
"""
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    base_url=os.environ["LLM_BASE_URL"],
    api_key=os.environ["LLM_API_KEY"],
)

res = client.chat.completions.create(
    model=os.environ["LLM_MODEL"],
    messages=[{"role": "user", "content": "Reply with exactly the word: ready"}],
)

print(res.choices[0].message.content)
