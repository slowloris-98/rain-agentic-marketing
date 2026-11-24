"""Signal layer: value scoring + conversion payloads for Google Data Manager and Meta CAPI."""
import hashlib
from datetime import datetime, timedelta, timezone

from . import settings

EPOCH = datetime(2026, 11, 2, tzinfo=timezone.utc)  # simulated day 0


def value_score(acct: dict, cfg: dict | None = None) -> float:
    """value = balance x monthly_margin x expected_tenure_months x (dd multiplier)."""
    cfg = cfg or settings.value_cfg()
    v = acct["balance"] * cfg["monthly_margin"][acct["product"]] * acct["tenure_months"]
    if acct["direct_deposit"]:
        v *= cfg["direct_deposit_multiplier"]
    return round(v, 2)


def first_year_value(acct: dict, cfg: dict | None = None) -> float:
    cfg = cfg or settings.value_cfg()
    v = acct["balance"] * cfg["monthly_margin"][acct["product"]] * min(12, acct["tenure_months"])
    return round(v * (cfg["direct_deposit_multiplier"] if acct["direct_deposit"] else 1), 2)


def _sha(s: str) -> str:
    return hashlib.sha256(s.strip().lower().encode()).hexdigest()


def _ts(day: int) -> datetime:
    return EPOCH + timedelta(days=day, hours=12)


def google_event(acct: dict, day: int, cfg: dict) -> dict:
    """One event for Data Manager API `events:ingest` (offline conversion with value)."""
    return {
        "transactionId": acct["click_id"],
        "eventTimestamp": _ts(day).isoformat().replace("+00:00", "Z"),
        "eventSource": "IN_STORE",
        "conversionValue": acct["value"],
        "currency": cfg["currency"],
        "adIdentifiers": {"gclid": acct["click_id"]},
        "userData": {"userIdentifiers": [{"emailAddress": _sha(acct["email"])}]},
    }


def meta_event(acct: dict, day: int, cfg: dict) -> dict:
    """One Conversions API event: physical_store, value + currency + predicted_ltv."""
    return {
        "event_name": "Purchase",
        "event_time": int(_ts(day).timestamp()),
        "event_id": acct["click_id"],
        "action_source": "physical_store",
        "user_data": {"em": [_sha(acct["email"])]},
        "custom_data": {
            "value": first_year_value(acct, cfg),
            "currency": cfg["currency"],
            "predicted_ltv": acct["value"],
            "content_category": acct["product"],
        },
    }
