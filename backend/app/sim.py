"""Synthetic credit union + ad traffic. Seeded and reproducible.

The per-segment truth (_truth) is HIDDEN: agents never import it. They only see spend,
clicks and the accounts that open, exactly like they would with a real core + ad platform.
"""
from functools import lru_cache
import hashlib

import numpy as np

PRODUCTS = ["checking", "savings", "cd", "money_market"]
CHANNELS = ["google", "meta"]
AUDIENCES = ["18-34", "35-54", "55+"]
GEOS = ["branch", "statewide"]


def arm_key(product, channel, audience, geo) -> str:
    return f"{product}|{channel}|{audience}|{geo}"


def all_arm_keys() -> list[str]:
    return [arm_key(p, c, a, g) for p in PRODUCTS for c in CHANNELS for a in AUDIENCES for g in GEOS]


def _h(*parts) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


@lru_cache(maxsize=4096)
def _truth(seed: int, key: str) -> dict:
    p, c, a, g = key.split("|")
    rng = np.random.default_rng([seed, _h(key)])
    cpc = {"google": 3.2, "meta": 1.4}[c] * (1.1 if g == "branch" else 1.0)
    cr = {"checking": 0.030, "savings": 0.025, "cd": 0.015, "money_market": 0.010}[p]
    cr *= {"google": 1.3, "meta": 0.7}[c]
    cr *= 1.3 if g == "branch" else 1.0
    if a == "18-34":
        cr *= 1.4 if p == "checking" else 0.8
    if a == "55+" and p in ("cd", "money_market"):
        cr *= 1.6
    cr *= float(rng.lognormal(0, 0.3))  # segment-specific surprise the allocator must discover
    bal = {"checking": 2500, "savings": 8000, "cd": 22000, "money_market": 30000}[p]
    bal *= {"18-34": 0.4, "35-54": 1.0, "55+": 1.8}[a]
    dd = (0.45 * (1.3 if a == "18-34" else 1.0)) if p == "checking" else 0.08
    tenure = {"checking": 48, "savings": 36, "cd": 24, "money_market": 40}[p] * (1.2 if a == "55+" else 1.0)
    return {
        "cpc": cpc,
        "ctr": {"google": 0.04, "meta": 0.012}[c],
        "cr": min(cr, 0.2),
        "bal_median": bal,
        "bal_sigma": 0.8,
        "dd_prob": min(dd, 0.9),
        "tenure_mean": tenure,
        "member_prob": 0.55 if g == "branch" else 0.30,
        "saturation": float(rng.uniform(150, 400)),  # $/day where returns start to flatten
    }


def run_arm(seed: int, day: int, key: str, spend: float, stream: int = 0) -> dict:
    """Simulate one arm for one day. stream=0 agentic run, 1 = fixed-split baseline."""
    t = _truth(seed, key)
    rng = np.random.default_rng([seed, day, _h(key), stream])
    effective = spend / (1 + spend / t["saturation"]) if spend > 0 else 0.0
    clicks = int(rng.poisson(effective / t["cpc"])) if effective > 0 else 0
    impressions = int(clicks / t["ctr"]) if clicks else int(effective / t["cpc"] / t["ctr"])
    n = int(rng.binomial(clicks, t["cr"])) if clicks else 0
    accounts = []
    for i in range(n):
        accounts.append({
            "click_id": f"{key}~{day}~{stream}~{i}",
            "product": key.split("|")[0],
            "balance": round(float(rng.lognormal(np.log(t["bal_median"]), t["bal_sigma"])), 2),
            "tenure_months": round(float(rng.gamma(2.0, t["tenure_mean"] / 2.0)), 1),
            "direct_deposit": bool(rng.random() < t["dd_prob"]),
            "member": bool(rng.random() < t["member_prob"]),
            "email": f"member{_h(seed, key, day, stream, i)}@example.com",
        })
    return {"spend": round(spend, 2), "impressions": impressions, "clicks": clicks, "accounts": accounts}


def run_day(seed: int, day: int, allocation: dict[str, float], stream: int = 0) -> dict[str, dict]:
    return {k: run_arm(seed, day, k, b, stream) for k, b in allocation.items()}
