"""
Generates synthetic customer transaction histories for the Transaction Risk
Investigation Assistant (PS06).

We use a deterministic, seeded generator rather than an LLM for the raw
transaction rows, because financial time-series need to be internally
consistent (running balances, plausible amounts, believable payees) and a
scripted generator gives us full control over which customers are "clean",
which are "suspicious", and which are "borderline" -- so we can demo all
three cases reliably. This is the "data and documents your system works
over" required by the submission rules; the LLM's job in this project is
report *reasoning*, not raw data fabrication.

Run: python scripts/generate_data.py
Writes: data/customers/<customer_id>.json  (one file per customer)
"""
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

random.seed(42)

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "customers"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CHANNELS = ["UPI", "NEFT", "IMPS", "Debit Card", "ATM", "Net Banking"]
CATEGORIES = ["Groceries", "Utilities", "Rent", "Dining", "Fuel", "Shopping",
              "Salary Credit", "Transfer", "Subscription", "Medical", "Travel"]
GEOS = ["Chennai", "Madurai", "Coimbatore", "Bengaluru"]

FIRST_NAMES = ["Arun", "Priya", "Karthik", "Divya", "Ramesh", "Sneha", "Vijay", "Anitha"]
LAST_NAMES = ["Kumar", "Raman", "Iyer", "Nair", "Pillai", "Subramanian"]


def rand_name():
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def make_txn(dt, amount, channel, category, payee, geo, txn_id):
    return {
        "txn_id": txn_id,
        "date": dt.strftime("%Y-%m-%d"),
        "time": dt.strftime("%H:%M"),
        "amount": round(amount, 2),
        "channel": channel,
        "category": category,
        "payee": payee,
        "geo": geo,
        "direction": "debit" if category != "Salary Credit" else "credit",
    }


def base_history(customer_id, name, months=4, monthly_txns=40, base_amount=2500, seed_offset=0):
    """Generates routine, unremarkable transaction history."""
    random.seed(42 + seed_offset)
    start = datetime.now() - timedelta(days=30 * months)
    txns = []
    txn_counter = 1
    payees = [f"{p} Store" for p in ["Ration", "Fuel", "Metro", "Cafe", "Pharmacy"]]
    home_geo = random.choice(GEOS)

    for m in range(months):
        salary_date = start + timedelta(days=30 * m + random.randint(0, 2))
        salary_date = salary_date.replace(hour=10, minute=0)
        txns.append(make_txn(salary_date, random.uniform(45000, 60000), "NEFT",
                              "Salary Credit", "Employer Pvt Ltd", home_geo,
                              f"{customer_id}-T{txn_counter:04d}"))
        txn_counter += 1

        for _ in range(monthly_txns):
            day_offset = random.randint(0, 29)
            hour = random.choice([9, 10, 11, 13, 14, 16, 18, 19, 20, 21])
            dt = start + timedelta(days=30 * m + day_offset)
            dt = dt.replace(hour=hour, minute=random.randint(0, 59))
            amount = max(50, random.gauss(base_amount, base_amount * 0.4))
            txns.append(make_txn(
                dt, amount, random.choice(CHANNELS), random.choice(CATEGORIES),
                random.choice(payees), home_geo, f"{customer_id}-T{txn_counter:04d}"
            ))
            txn_counter += 1

    txns.sort(key=lambda t: (t["date"], t["time"]))
    return txns, txn_counter, home_geo


def customer_clean():
    """CUST001 -- entirely routine activity. Should come back clean."""
    cid, name = "CUST001", rand_name()
    txns, _, geo = base_history(cid, name, months=4, monthly_txns=35, base_amount=2200, seed_offset=1)
    return {"customer_id": cid, "name": name, "home_geo": geo, "transactions": txns}


def customer_suspicious():
    """CUST002 -- routine baseline, then a clear multi-rule incident near the end."""
    cid, name = "CUST002", rand_name()
    txns, counter, geo = base_history(cid, name, months=4, monthly_txns=35, base_amount=2400, seed_offset=2)

    last_date = datetime.strptime(txns[-1]["date"], "%Y-%m-%d")
    incident_start = last_date + timedelta(days=2)

    txns.append(make_txn(incident_start.replace(hour=23, minute=10), 185000, "IMPS",
                          "Transfer", "Rahul Verma", "Unknown", f"{cid}-T{counter:04d}"))
    counter += 1

    new_payee = "QuickPay Merchant 7781"
    for i in range(4):
        dt = incident_start + timedelta(hours=1 + i * 6)
        dt = dt.replace(hour=random.choice([1, 2, 3]), minute=random.randint(0, 59))
        txns.append(make_txn(dt, random.uniform(18000, 24000), "UPI", "Transfer",
                              new_payee, "Unknown", f"{cid}-T{counter:04d}"))
        counter += 1

    txns.append(make_txn(incident_start + timedelta(hours=30), 42000, "Net Banking",
                          "Crypto Exchange", "CoinDesk Exchange Ltd", "Unknown",
                          f"{cid}-T{counter:04d}"))
    counter += 1

    txns.sort(key=lambda t: (t["date"], t["time"]))
    return {"customer_id": cid, "name": name, "home_geo": geo, "transactions": txns}


def customer_borderline():
    """CUST003 -- a couple of mildly unusual transactions that don't clearly
    cross any rule threshold. Good for demoing calibrated, non-alarmist output."""
    cid, name = "CUST003", rand_name()
    txns, counter, geo = base_history(cid, name, months=4, monthly_txns=32, base_amount=3000, seed_offset=3)

    last_date = datetime.strptime(txns[-1]["date"], "%Y-%m-%d")
    dt = (last_date + timedelta(days=3)).replace(hour=20, minute=15)
    txns.append(make_txn(dt, 34000, "IMPS", "Transfer", "Family Member - Deepa",
                          geo, f"{cid}-T{counter:04d}"))
    counter += 1
    dt2 = (last_date + timedelta(days=5)).replace(hour=23, minute=40)
    txns.append(make_txn(dt2, 5200, "UPI", "Dining", "Night Cafe", geo, f"{cid}-T{counter:04d}"))

    txns.sort(key=lambda t: (t["date"], t["time"]))
    return {"customer_id": cid, "name": name, "home_geo": geo, "transactions": txns}


def main():
    customers = [customer_clean(), customer_suspicious(), customer_borderline()]
    for c in customers:
        path = OUT_DIR / f"{c['customer_id']}.json"
        with open(path, "w") as f:
            json.dump(c, f, indent=2)
        print(f"Wrote {path} ({len(c['transactions'])} transactions)")


if __name__ == "__main__":
    main()