"""CRM stub: the customer banks and credit unions RAIN serves.

Fixed facts (products, APY, minimum balance, fees, disclosures, branches, region, brand voice)
come from here, never from code or the LLM. Today this reads a static JSON file; to go live,
replace the body of `_load()` with a call to the real CRM. Callers only use list/get.
"""
import json
from functools import lru_cache
from pathlib import Path

FILE = Path(__file__).with_name("customers.json")


@lru_cache(maxsize=1)
def _load() -> tuple[dict, ...]:
    return tuple(json.loads(FILE.read_text()))


def list_customers() -> list[dict]:
    return [dict(c) for c in _load()]


def get_customer(customer_id: str) -> dict:
    for c in _load():
        if c["id"] == customer_id:
            return json.loads(json.dumps(c))  # deep copy: callers may snapshot/mutate
    raise KeyError(f"Unknown customer: {customer_id}")
