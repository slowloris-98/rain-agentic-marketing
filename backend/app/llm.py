"""The single entry point for every LLM call.

- Structured JSON out (output_config.format) so agents never parse free text.
- Deterministic `fallback()` when there's no API key or the call fails/refuses, so the
  demo always runs.
- LangSmith later: decorate `call` with `@langsmith.traceable(run_type="llm")`.
"""
import json
import logging
from typing import Callable

from . import settings

log = logging.getLogger("llm")
_client = None
_openai_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def _get_openai():
    global _openai_client
    if _openai_client is None:
        import openai
        _openai_client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
    return _openai_client


def _openai(name: str, system: str, prompt: str, schema: dict, fallback: Callable[[], dict]) -> tuple[dict, str]:
    """Same contract as the Anthropic path; strict json_schema works because llm.obj schemas
    mark every field required and forbid additional properties."""
    try:
        resp = _get_openai().chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            response_format={"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}},
        )
        msg = resp.choices[0].message
        if getattr(msg, "refusal", None):
            log.warning("%s: refusal, using template", name)
            return fallback(), "template"
        return json.loads(msg.content), "llm"
    except Exception as e:  # network/auth/schema errors must not stop a cycle
        log.warning("%s: OpenAI call failed (%s), using template", name, e)
        return fallback(), "template"


def call(name: str, system: str, prompt: str, schema: dict, fallback: Callable[[], dict]) -> tuple[dict, str]:
    """Returns (data, source) where source is 'llm' or 'template'."""
    provider = settings.llm_provider()
    if provider is None:
        return fallback(), "template"
    if provider == "openai":
        return _openai(name, system, prompt, schema, fallback)
    try:
        resp = _get_client().beta.messages.create(
            model=settings.LLM_MODEL,
            max_tokens=8000,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            # Server-side fallback: if the request is refused, the API retries on a fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if resp.stop_reason == "refusal":
            log.warning("%s: refusal, using template", name)
            return fallback(), "template"
        text = next(b.text for b in resp.content if b.type == "text")
        return json.loads(text), "llm"
    except Exception as e:  # network/auth/schema errors must not stop a cycle
        log.warning("%s: LLM call failed (%s), using template", name, e)
        return fallback(), "template"


def obj(props: dict, required: list[str] | None = None) -> dict:
    """Small helper for strict JSON schemas."""
    return {"type": "object", "properties": props, "required": required or list(props),
            "additionalProperties": False}
