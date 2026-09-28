"""
W7 Stage 5: runs every case in cases.json against a live /triage endpoint
and reports how many were classified correctly. "It gave a good answer
when I tried it" is not evidence -- this is.

Usage:
    # with the server already running (LLM_STUB unset, a real key in .env)
    python evals/run_evals.py
    python evals/run_evals.py --base-url http://localhost:8000

Uses only the standard library on purpose, so running the eval never
depends on anything beyond what's already required to run the server.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

CASES_PATH = Path(__file__).parent / "cases.json"


def run(base_url: str) -> int:
    cases = json.loads(CASES_PATH.read_text())
    category_matches = 0
    urgency_matches = 0
    failures = []

    for case in cases:
        payload = json.dumps({"text": case["text"]}).encode()
        req = urllib.request.Request(
            f"{base_url}/triage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=35) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            failures.append((case["id"], f"HTTP {e.code}: {e.read().decode()[:200]}"))
            continue
        except urllib.error.URLError as e:
            print(f"Could not reach {base_url} — is the server running? ({e})", file=sys.stderr)
            return 1

        cat_ok = body.get("category") == case["expected_category"]
        urg_ok = body.get("urgency") == case["expected_urgency"]
        category_matches += cat_ok
        urgency_matches += urg_ok

        status = "OK  " if cat_ok else "MISS"
        print(
            f"[{status}] case {case['id']}: expected category={case['expected_category']!r}, "
            f"got {body.get('category')!r} (urgency expected={case['expected_urgency']!r}, "
            f"got {body.get('urgency')!r}) — {case['note']}"
        )
        if not cat_ok:
            failures.append((case["id"], f"expected {case['expected_category']}, got {body.get('category')}"))

    total = len(cases)
    print()
    print(f"Category score: {category_matches}/{total}")
    print(f"Urgency score:  {urgency_matches}/{total}")
    if failures:
        print("\nFailed cases:")
        for case_id, reason in failures:
            print(f"  - case {case_id}: {reason}")

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    sys.exit(run(args.base_url))
