"""All configuration comes from env vars (optionally a backend/.env file)."""

import os
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "config"

_env = BASE.parent / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


MODE = env("MODE", "sandbox")  # sandbox | live
DATABASE_URL = env("DATABASE_URL", "sqlite:///./rain.db")
JWT_SECRET = env("JWT_SECRET", "dev-secret-change-me-in-production-0001")
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
LLM_MODEL = env("LLM_MODEL", "claude-opus-5-5")
OPENAI_API_KEY = env("OPENAI_API_KEY")
OPENAI_MODEL = env("OPENAI_MODEL", "gpt-4.1")
LLM_PROVIDER = env("LLM_PROVIDER", "").strip().lower()  # anthropic | openai | empty = auto


def llm_provider() -> str | None:
    """Which LLM the agents use: the one LLM_PROVIDER names (if its key is set), otherwise the
    first provider with a key. None = no key, agents use their deterministic templates."""
    keys = {"anthropic": ANTHROPIC_API_KEY, "openai": OPENAI_API_KEY}
    if LLM_PROVIDER in keys:
        return LLM_PROVIDER if keys[LLM_PROVIDER] else None
    return next((p for p, k in keys.items() if k), None)
TICK_SECONDS = float(env("TICK_SECONDS", "0"))

# Demo users. Replace with a users table when real auth is needed.
# Clients map to a CRM customer; they always see that customer's latest run.
USERS = {
    "admin@rain": {"password": env("ADMIN_PASSWORD", "admin"), "role": "admin", "crm_id": None},
    "client@acme": {"password": env("CLIENT_PASSWORD", "client"), "role": "client", "crm_id": "acme-ccu"},
}


def value_cfg() -> dict:
    return yaml.safe_load((CONFIG / "value.yaml").read_text())


def policy() -> dict:
    return yaml.safe_load((CONFIG / "policy.yaml").read_text())


def save_policy(p: dict) -> None:
    (CONFIG / "policy.yaml").write_text(yaml.safe_dump(p, sort_keys=False))
