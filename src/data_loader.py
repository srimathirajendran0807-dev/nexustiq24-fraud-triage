import json
from pathlib import Path
from functools import lru_cache
from typing import List, Dict, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@lru_cache(maxsize=1)
def load_rules() -> List[dict]:
    with open(DATA_DIR / "rules.json") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_all_customers() -> Dict[str, dict]:
    customers = {}
    customers_dir = DATA_DIR / "customers"
    for path in sorted(customers_dir.glob("*.json")):
        with open(path) as f:
            c = json.load(f)
            customers[c["customer_id"]] = c
    return customers


def get_customer(customer_id: str) -> Optional[dict]:
    return load_all_customers().get(customer_id)


def list_customers() -> List[dict]:
    return [
        {"customer_id": c["customer_id"], "name": c["name"], "transaction_count": len(c["transactions"])}
        for c in load_all_customers().values()
    ]