"""
PS06 - Transaction Risk Investigation Assistant
Single entry point: `python app.py` serves API + frontend on port 8000.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
def _load_dotenv():
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

import os
_load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
import uvicorn

from src import data_loader, rules_engine, llm
from src.models import InvestigateRequest, InvestigationReport, Finding

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Transaction Risk Investigation Assistant")
templates = Jinja2Templates(directory=str(BASE_DIR / "frontend" / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "frontend" / "static")), name="static")

RULE_NAME_BY_ID = {r["rule_id"]: r["name"] for r in data_loader.load_rules()}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    customers = data_loader.list_customers()
    return templates.TemplateResponse("index.html", {"request": request, "customers": customers})


@app.get("/api/customers")
def api_list_customers():
    return data_loader.list_customers()


@app.post("/api/investigate", response_model=InvestigationReport)
def api_investigate(req: InvestigateRequest):
    customer = data_loader.get_customer(req.customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail=f"No customer found with id '{req.customer_id}'")

    rules = data_loader.load_rules()

    try:
        det_result = rules_engine.investigate(customer["transactions"], rules)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Rules engine error: {e}")

    findings = det_result["findings"]

    narrative = None
    if findings:
        narrative = llm.generate_investigation_narrative(req.customer_id, findings)

    narrative_available = narrative is not None

    if not findings:
        overall_assessment = "No activity matching any risk rule was found in this customer's history. Nothing requires investigator attention."
        priority = "none"
        narrative_by_key = {}
    elif narrative:
        overall_assessment = narrative.get("overall_assessment", "Findings detected; see details below.")
        priority = narrative.get("priority", "medium")
        narrative_by_key = {
            (n["rule_id"], tuple(sorted(n["txn_ids"]))): n for n in narrative.get("narrative_findings", [])
        }
    else:
        overall_assessment = (
            f"{len(findings)} rule-based finding(s) detected. Automated narrative generation is "
            "unavailable right now (LLM call failed or no API key set) -- raw rule findings below "
            "are still fully valid and traceable."
        )
        priority = "medium"
        narrative_by_key = {}

    report_findings = []
    for f in findings:
        key = (f["rule_id"], tuple(sorted(f["txn_ids"])))
        n = narrative_by_key.get(key)
        report_findings.append(Finding(
            rule_id=f["rule_id"],
            rule_name=RULE_NAME_BY_ID.get(f["rule_id"], f["rule_id"]),
            txn_ids=f["txn_ids"],
            evidence=f["evidence"],
            explanation=(n or {}).get("explanation"),
            what_to_check_first=(n or {}).get("what_to_check_first"),
        ))

    return InvestigationReport(
        customer_id=customer["customer_id"],
        customer_name=customer["name"],
        overall_assessment=overall_assessment,
        priority=priority,
        has_findings=bool(findings),
        findings=report_findings,
        transactions_reviewed=len(customer["transactions"]),
        llm_narrative_available=narrative_available,
    )


@app.get("/api/customers/{customer_id}/transactions")
def api_customer_transactions(customer_id: str):
    customer = data_loader.get_customer(customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail=f"No customer found with id '{customer_id}'")
    return customer["transactions"]


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)