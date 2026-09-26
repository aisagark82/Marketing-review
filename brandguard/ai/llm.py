"""The one place BrandGuard talks to Gemini: limits, retries, logging, caching, JSON parsing.

Everything else calls Gemini.generate_json(); no other module imports the Google SDK.
"""

import hashlib
import logging
import os
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from datetime import time as day_start

import httpx
import truststore
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select

from brandguard.ai.config import AISettings, load_ai_settings, load_api_key
from brandguard.core.db import session_scope
from brandguard.core.models import AICache, AICall

log = logging.getLogger(__name__)

RETRY_DELAYS_S = (2, 4, 8, 16)  # on 429 / 5xx
RETRYABLE = frozenset({429, 500, 502, 503, 504})
TIMEOUT_S = 90
# Marketing and pharma copy (dosages, side effects) can trip the default filters; the content
# is public, so only block what's clearly harmful.
RELAXED_SAFETY = [
    types.SafetySetting(category=category, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH)
    for category in (
        types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
    )
]


class AIUnavailable(Exception):
    """No API key, or Gemini refused the key."""


class AILimitReached(Exception):
    """The daily request limit from Settings is used up; AI steps pause until tomorrow."""


class AIResponseError(Exception):
    """Gemini answered, but not with the JSON asked for."""


@dataclass
class Image:
    data: bytes
    mime_type: str


@dataclass
class Result:
    data: BaseModel
    input_tokens: int = 0
    output_tokens: int = 0
    cached: bool = False


def _cache_key(model: str, stage: str, system: str, parts: list) -> str:
    digest = hashlib.sha256()
    for piece in (model, stage, system):
        digest.update(piece.encode())
    for part in parts:
        digest.update(
            hashlib.sha256(part.data).digest() if isinstance(part, Image) else part.encode()
        )
    return digest.hexdigest()


def requests_today() -> int:
    midnight = datetime.combine(datetime.now(UTC).date(), day_start(), tzinfo=UTC)
    with session_scope() as session:
        return session.scalar(select(func.count(AICall.id)).where(AICall.created_at >= midnight))


def _log_call(
    stage: str, model: str, run_id: int | None, started: float, usage=None, error: str | None = None
) -> None:
    with session_scope() as session:
        session.add(
            AICall(
                stage=stage,
                model=model,
                run_id=run_id,
                input_tokens=(usage.prompt_token_count or 0) if usage else 0,
                # Thinking tokens are billed as output.
                output_tokens=(
                    (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
                )
                if usage
                else 0,
                latency_ms=int((time.monotonic() - started) * 1000),
                ok=error is None,
                error=error,
            )
        )


class Gemini:
    def __init__(self, api_key: str, settings: AISettings):
        self.settings = settings
        self.model = settings.model
        # Same trust store as the crawler (corporate TLS inspection works); base URL can be
        # pointed at a local fake server in tests.
        http_client = httpx.Client(
            verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT), timeout=TIMEOUT_S
        )
        options = types.HttpOptions(httpx_client=http_client)
        if base_url := os.environ.get("BRANDGUARD_GEMINI_BASE_URL"):
            options.base_url = base_url
        self._client = genai.Client(api_key=api_key, http_options=options)
        self._last_request = 0.0

    def _pace(self) -> None:
        interval = 60 / self.settings.requests_per_minute
        wait = interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _config(self, system: str, schema: type[BaseModel], max_output_tokens: int):
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0,
            max_output_tokens=max_output_tokens,
            safety_settings=RELAXED_SAFETY,
        )
        # Flash models can skip "thinking", which these short, well-specified tasks don't need
        # (it would triple the output tokens). Pro models can't turn it off, so leave them be.
        if "flash" in self.model:
            config.thinking_config = types.ThinkingConfig(thinking_budget=0)
        return config

    def generate_json(
        self,
        stage: str,
        system: str,
        parts: list,
        schema: type[BaseModel],
        *,
        max_output_tokens: int = 1024,
        run_id: int | None = None,
        use_cache: bool = True,
    ) -> Result:
        """One structured call. Cached by model + prompt + input; retried on 429/5xx."""
        key = _cache_key(self.model, stage, system, parts)
        if use_cache:
            with session_scope() as session:
                hit = session.get(AICache, key)
                if hit is not None:
                    return Result(schema.model_validate(hit.response), cached=True)
        if requests_today() >= self.settings.daily_request_limit:
            raise AILimitReached(
                f"The daily limit of {self.settings.daily_request_limit} Gemini requests is used up"
            )

        contents = [
            types.Part.from_bytes(data=p.data, mime_type=p.mime_type)
            if isinstance(p, Image)
            else types.Part.from_text(text=p)
            for p in parts
        ]
        config = self._config(system, schema, max_output_tokens)
        for attempt, delay in enumerate((*RETRY_DELAYS_S, None)):
            self._pace()
            started = time.monotonic()
            try:
                response = self._client.models.generate_content(
                    model=self.model, contents=contents, config=config
                )
            except errors.APIError as exc:
                _log_call(stage, self.model, run_id, started, error=f"{exc.code}: {exc.message}")
                if exc.code in (400, 401, 403) and "API key" in (exc.message or ""):
                    raise AIUnavailable(f"Gemini rejected the API key: {exc.message}") from exc
                if exc.code in RETRYABLE and delay is not None:
                    log.warning(
                        "Gemini %s (attempt %d), retrying in %ss", exc.code, attempt + 1, delay
                    )
                    time.sleep(delay)
                    continue
                raise
            except httpx.HTTPError as exc:
                _log_call(stage, self.model, run_id, started, error=f"{type(exc).__name__}: {exc}")
                if delay is not None:
                    time.sleep(delay)
                    continue
                raise AIUnavailable(f"Could not reach Gemini: {exc}") from exc
            _log_call(stage, self.model, run_id, started, usage=response.usage_metadata)
            break

        try:
            data = schema.model_validate_json(response.text or "")
        except ValidationError as exc:
            raise AIResponseError(
                f"Gemini's answer didn't match the expected format: {(response.text or '')[:300]!r}"
            ) from exc
        if use_cache:
            with session_scope() as session:
                session.merge(AICache(key=key, stage=stage, response=data.model_dump()))
        usage = response.usage_metadata
        return Result(
            data,
            input_tokens=(usage.prompt_token_count or 0) if usage else 0,
            output_tokens=(usage.candidates_token_count or 0) if usage else 0,
        )

    def list_models(self) -> list[str]:
        """Models this key can use for generateContent, e.g. 'gemini-2.5-flash'."""
        names = []
        for model in self._client.models.list():
            actions = model.supported_actions or []
            if "generateContent" in actions and model.name:
                names.append(model.name.removeprefix("models/"))
        return sorted(names)


def open_gemini(session) -> Gemini | None:
    """A client from the saved key and settings, or None when no key is set."""
    key, _ = load_api_key(session)
    return Gemini(key, load_ai_settings(session)) if key else None
