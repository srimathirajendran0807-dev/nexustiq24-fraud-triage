from typing import List, Optional
from pydantic import BaseModel


class CustomerSummary(BaseModel):
    customer_id: str
    name: str
    transaction_count: int


class InvestigateRequest(BaseModel):
    customer_id: str


class Finding(BaseModel):
    rule_id: str
    rule_name: str
    txn_ids: List[str]
    evidence: dict
    explanation: Optional[str] = None
    what_to_check_first: Optional[str] = None


class InvestigationReport(BaseModel):
    customer_id: str
    customer_name: str
    overall_assessment: str
    priority: str
    has_findings: bool
    findings: List[Finding]
    transactions_reviewed: int
    llm_narrative_available: bool