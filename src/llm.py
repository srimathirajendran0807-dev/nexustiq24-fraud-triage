"""
Gemini-backed narrative layer -- calls the Gemini REST API directly via
`requests`, avoiding the google-generativeai SDK (which requires a newer
Python than some environments have). This is a fully supported way to use
the Gemini API.

CRITICAL DESIGN CONSTRAINT: this module never decides *whether* something is
suspicious -- src/rules_engine.py already did that, deterministically,
before this module is even called. The LLM's only job is to turn a
structured list of rule findings into a readable investigation report,
grounded strictly in that input.

If the Gemini call fails or the API key is missing, we fail gracefully:
the deterministic findings are still returned to the caller, and the API
layer marks the narrative as unavailable rather than crashing or
fabricating a report.
"""
import json
import os
from typing import Optional, List, Dict

import requests

MODEL_NAME = "gemini-3.6-flash"
API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

_SYSTEM_INSTRUCTION = """You are a fraud-desk report writer for a bank's transaction risk investigation \
assistant. You are given the customer's ID and a list of deterministic rule findings that were ALREADY \
computed by a separate rules engine -- you did not compute them and must not add, remove, or reinterpret \
findings. Your job is only to explain them clearly.

Hard constraints:
- Never state that fraud has occurred. You flag, explain, and hand judgement to a human investigator.
- Every claim in your output must cite the rule_id and the exact txn_ids provided in the findings. \
Never reference a transaction ID that isn't in the input.
- If the findings list is empty, your overall_assessment must clearly state nothing needs attention -- \
do not manufacture concern.
- Do not diagnose intent. Describe the pattern and the deviation from the customer's own established \
behaviour only.
- Respond with ONLY valid JSON matching the schema given. No markdown fences, no preamble.
"""

_RESPONSE_SCHEMA_HINT = """
Return JSON with this exact shape:
{
  "overall_assessment": "one or two sentences: does anything need attention, in plain language",
  "narrative_findings": [
    {
      "rule_id": "<must match an input finding's rule_id>",
      "txn_ids": ["<must match that finding's txn_ids exactly>"],
      "explanation": "plain-language explanation of what happened and why it deviates from this customer's normal pattern",
      "what_to_check_first": "concrete next step for the investigator"
    }
  ],
  "priority": "none | low | medium | high"
}
"""


def _log_debug(message: str) -> None:
    print(message, flush=True)
    try:
        with open("llm_debug.log", "a", encoding="utf-8") as f:
            f.write(message + "\n")
    except Exception:
        pass


def generate_investigation_narrative(customer_id: str, findings: List[dict]) -> Optional[dict]:
    """Calls Gemini via plain REST to narrate the findings. Returns None on
    any failure so the caller can degrade gracefully."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        _log_debug("[llm] No GEMINI_API_KEY found in environment. Skipping narrative call.")
        return None

    payload_data = {"customer_id": customer_id, "findings": findings}
    prompt = (
        _SYSTEM_INSTRUCTION
        + "\n\nDeterministic findings (ground truth -- do not alter):\n"
        + json.dumps(payload_data, indent=2, default=str)
        + "\n\n" + _RESPONSE_SCHEMA_HINT
    )

    url = API_URL_TEMPLATE.format(model=MODEL_NAME, key=api_key)
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }

    try:
        resp = requests.post(url, json=body, timeout=60)
        if not resp.ok:
            _log_debug(f"[llm] Gemini HTTP error {resp.status_code}: {resp.text[:500]}")
            resp.raise_for_status()
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        parsed = json.loads(text)
        return _validate_narrative(parsed, findings)
    except Exception as e:  # noqa: BLE001
        _log_debug(f"[llm] Gemini call failed, degrading to rules-only output: {e}")
        return None


def _validate_narrative(parsed: dict, findings: List[dict]) -> Optional[dict]:
    """Cross-checks the LLM's cited txn_ids actually exist in the
    deterministic findings, so a hallucinated citation can never reach the
    user. Drops any narrative item that doesn't check out."""
    valid_txn_ids = {tid for f in findings for tid in f["txn_ids"]}

    clean_narrative = []
    for item in parsed.get("narrative_findings", []):
        txn_ids = item.get("txn_ids", [])
        if not txn_ids or not all(t in valid_txn_ids for t in txn_ids):
            continue
        clean_narrative.append(item)

    parsed["narrative_findings"] = clean_narrative
    return parsed