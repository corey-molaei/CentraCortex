from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decrypt_secret
from app.models.llm_call_log import LLMCallLog
from app.models.llm_provider import LLMProvider
from app.services.llm_codex_oauth import get_valid_access_token

logger = structlog.get_logger(__name__)

SECRET_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b(authorization\s*:\s*bearer)\s+[^\s,;]+"), r"\1 [REDACTED]"),
    (re.compile(r"(?i)(['\"]authorization['\"]\s*:\s*['\"]bearer\s+)[^'\"]+(['\"])"), r"\1[REDACTED]\2"),
    (re.compile(r"\bsk-[A-Za-z0-9]{8,}\b"), "sk-[REDACTED]"),
    (
        re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password|token)\b\s*[:=]\s*([^\s,;]+)"),
        r"\1=[REDACTED]",
    ),
    (
        re.compile(
            r"(?i)(['\"](?:api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password|token)['\"]\s*:\s*['\"])([^'\"]+)(['\"])"
        ),
        r"\1[REDACTED]\3",
    ),
)


class LLMRouter:
    def __init__(self, db: Session, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id

    def list_providers(self) -> list[LLMProvider]:
        return self.db.execute(
            select(LLMProvider).where(LLMProvider.tenant_id == self.tenant_id).order_by(LLMProvider.created_at)
        ).scalars().all()

    def select_provider(self, provider_id_override: str | None = None) -> tuple[LLMProvider, LLMProvider | None]:
        providers = self.list_providers()
        if not providers:
            raise ValueError("No LLM providers configured for tenant")

        selected: LLMProvider | None = None
        fallback: LLMProvider | None = None

        if provider_id_override:
            selected = next((p for p in providers if p.id == provider_id_override), None)
            if not selected:
                raise ValueError("Provider override not found for tenant")
        else:
            selected = next((p for p in providers if p.is_default), None) or providers[0]

        fallback = next((p for p in providers if p.is_fallback and p.id != selected.id), None)
        return selected, fallback

    def _enforce_rate_limit(self, provider: LLMProvider) -> None:
        one_minute_ago = datetime.now(timezone.utc) - timedelta(minutes=1)
        count = self.db.execute(
            select(func.count(LLMCallLog.id)).where(
                LLMCallLog.tenant_id == self.tenant_id,
                LLMCallLog.provider_id == provider.id,
                LLMCallLog.created_at >= one_minute_ago,
            )
        ).scalar_one()

        if count >= provider.rate_limit_rpm:
            raise ValueError(f"Rate limit exceeded for provider {provider.name}")

    def _should_omit_temperature(self, provider: LLMProvider) -> bool:
        provider_type = (provider.provider_type or "").lower()
        if provider_type not in {"openai", "vllm", "other"}:
            return False
        model_name = (provider.model_name or "").strip().lower()
        return model_name == "gpt-5-nano" or model_name.startswith("gpt-5-nano-")

    def _openai_compatible_call(
        self,
        provider: LLMProvider,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> dict[str, Any]:
        provider_type = provider.provider_type.lower()
        if provider_type == "codex":
            bearer_token = get_valid_access_token(self.db, self.tenant_id)
        else:
            bearer_token = decrypt_secret(provider.api_key_encrypted) if provider.api_key_encrypted else ""
        headers = {
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {bearer_token}"} if bearer_token else {}),
        }

        url = f"{provider.base_url.rstrip('/')}/v1/chat/completions"
        payload = {
            "model": provider.model_name,
            "messages": messages,
        }
        if not self._should_omit_temperature(provider):
            payload["temperature"] = temperature

        with httpx.Client(timeout=30) as client:
            response = client.post(url, headers=headers, json=payload)
            if response.status_code >= 400:
                detail = self._extract_error_detail(response)
                raise ValueError(f"OpenAI-compatible request failed ({response.status_code}): {detail}")
            data = response.json()

        usage = data.get("usage", {})
        total_tokens = usage.get("total_tokens", 0)
        return {
            "answer": data["choices"][0]["message"]["content"],
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": total_tokens,
            "cost_usd": round(total_tokens * 0.000002, 6),
        }

    def _responses_output_text(self, payload: dict[str, Any]) -> str:
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text

        chunks: list[str] = []
        for item in payload.get("output", []) or []:
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []) or []:
                if not isinstance(content, dict):
                    continue
                content_type = str(content.get("type") or "").lower()
                if content_type in {"output_text", "text"}:
                    text = content.get("text")
                    if isinstance(text, str) and text:
                        chunks.append(text)
        return "\n".join(chunks).strip()

    def _codex_call(
        self,
        provider: LLMProvider,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> dict[str, Any]:
        bearer_token = get_valid_access_token(self.db, self.tenant_id)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {bearer_token}",
        }

        input_items: list[dict[str, Any]] = []
        for message in messages:
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            role = str(message.get("role") or "user")
            input_items.append(
                {
                    "role": role,
                    "content": [{"type": "input_text", "text": content}],
                }
            )

        if not input_items:
            input_items = [{"role": "user", "content": [{"type": "input_text", "text": "Hello"}]}]

        url = f"{provider.base_url.rstrip('/')}/v1/responses"
        payload = {
            "model": provider.model_name,
            "input": input_items,
            "temperature": temperature,
        }

        with httpx.Client(timeout=30) as client:
            response = client.post(url, headers=headers, json=payload)
            if response.status_code >= 400:
                detail = self._extract_error_detail(response)
                raise ValueError(f"Codex request failed ({response.status_code}): {detail}")
            data = response.json()

        usage = data.get("usage", {}) or {}
        prompt_tokens = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
        completion_tokens = int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
        total_tokens = int(usage.get("total_tokens", prompt_tokens + completion_tokens) or 0)

        return {
            "answer": self._responses_output_text(data),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost_usd": round(total_tokens * 0.000002, 6),
        }

    def _ollama_call(self, provider: LLMProvider, messages: list[dict[str, str]], temperature: float) -> dict[str, Any]:
        url = f"{provider.base_url.rstrip('/')}/api/chat"
        payload = {
            "model": provider.model_name,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }

        with httpx.Client(timeout=30) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        prompt_tokens = data.get("prompt_eval_count", 0)
        completion_tokens = data.get("eval_count", 0)
        total_tokens = prompt_tokens + completion_tokens

        return {
            "answer": data.get("message", {}).get("content", ""),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost_usd": 0.0,
        }

    def _call_provider(
        self,
        provider: LLMProvider,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> dict[str, Any]:
        self._enforce_rate_limit(provider)

        provider_type = provider.provider_type.lower()
        if provider_type in {"openai", "vllm", "other"}:
            return self._openai_compatible_call(provider, messages, temperature)
        if provider_type == "codex":
            return self._codex_call(provider, messages, temperature)
        if provider_type == "ollama":
            return self._ollama_call(provider, messages, temperature)
        raise ValueError(f"Unsupported provider type: {provider.provider_type}")

    def _log_call(
        self,
        *,
        provider: LLMProvider | None,
        model_name: str,
        status: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        cost_usd: float = 0.0,
        response_ms: int = 0,
        error_message: str | None = None,
    ) -> None:
        self.db.add(
            LLMCallLog(
                tenant_id=self.tenant_id,
                provider_id=provider.id if provider else None,
                model_name=model_name,
                status=status,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                cost_usd=cost_usd,
                response_ms=response_ms,
                error_message=error_message,
            )
        )
        self.db.commit()

    def _prompt_debug_logging_enabled(self) -> bool:
        return settings.prompt_debug_logging_enabled and settings.log_level.upper() == "DEBUG"

    def _redact_secrets(self, value: str) -> str:
        redacted = value
        for pattern, replacement in SECRET_REPLACEMENTS:
            redacted = pattern.sub(replacement, redacted)
        return redacted

    def _sanitize_messages_for_log(self, messages: list[dict[str, str]]) -> list[dict[str, Any]]:
        max_chars = max(1, settings.prompt_debug_logging_max_chars_per_message)
        sanitized: list[dict[str, Any]] = []
        for index, message in enumerate(messages):
            normalized = dict(message)
            content = str(normalized.get("content") or "")
            redacted = self._redact_secrets(content)
            truncated = len(redacted) > max_chars
            if truncated:
                redacted = f"{redacted[:max_chars]}..."
            normalized["content"] = redacted
            normalized["message_index"] = index
            normalized["content_len"] = len(content)
            normalized["truncated"] = truncated
            sanitized.append(normalized)
        return sanitized

    def _log_prompt_debug(
        self,
        *,
        provider: LLMProvider,
        messages: list[dict[str, str]],
        attempt_index: int,
        is_fallback_attempt: bool,
        error: str | None = None,
    ) -> None:
        if not self._prompt_debug_logging_enabled():
            return
        payload = {
            "tenant_id": self.tenant_id,
            "provider_id": provider.id,
            "provider_name": provider.name,
            "provider_type": provider.provider_type,
            "model_name": provider.model_name,
            "attempt_index": attempt_index,
            "is_fallback_attempt": is_fallback_attempt,
            "message_count": len(messages),
            "messages": self._sanitize_messages_for_log(messages),
        }
        if error is None:
            logger.debug("llm_prompt_debug", **payload)
        else:
            logger.debug("llm_prompt_debug_error", error=error, **payload)

    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float,
        provider_id_override: str | None = None,
        allow_fallback: bool = True,
    ) -> tuple[LLMProvider, dict[str, Any]]:
        primary, fallback = self.select_provider(provider_id_override)
        providers = [primary, fallback] if allow_fallback else [primary]

        for attempt_index, provider in enumerate(providers, start=1):
            if provider is None:
                continue
            is_fallback_attempt = allow_fallback and fallback is not None and provider.id == fallback.id
            self._log_prompt_debug(
                provider=provider,
                messages=messages,
                attempt_index=attempt_index,
                is_fallback_attempt=is_fallback_attempt,
            )
            started = time.perf_counter()
            try:
                result = self._call_provider(provider, messages, temperature)
                response_ms = int((time.perf_counter() - started) * 1000)
                self._log_call(
                    provider=provider,
                    model_name=provider.model_name,
                    status="success",
                    prompt_tokens=result["prompt_tokens"],
                    completion_tokens=result["completion_tokens"],
                    total_tokens=result["total_tokens"],
                    cost_usd=result["cost_usd"],
                    response_ms=response_ms,
                )
                return provider, result
            except Exception as exc:
                response_ms = int((time.perf_counter() - started) * 1000)
                self._log_call(
                    provider=provider,
                    model_name=provider.model_name,
                    status="error",
                    response_ms=response_ms,
                    error_message=str(exc),
                )
                self._log_prompt_debug(
                    provider=provider,
                    messages=messages,
                    attempt_index=attempt_index,
                    is_fallback_attempt=is_fallback_attempt,
                    error=str(exc),
                )
                if not allow_fallback or provider == fallback or fallback is None:
                    raise

        raise RuntimeError("No provider available")

    def test_connection(self, provider: LLMProvider) -> tuple[bool, str]:
        try:
            provider_type = provider.provider_type.lower()
            if provider_type == "codex":
                self._codex_call(
                    provider,
                    messages=[{"role": "user", "content": "Connection test"}],
                    temperature=0.0,
                )
            elif provider_type in {"openai", "vllm", "other"}:
                # Validate the configured model on the same endpoint family used by chat runtime.
                self._openai_compatible_call(
                    provider,
                    messages=[{"role": "user", "content": "Connection test"}],
                    temperature=0.0,
                )
            elif provider_type == "ollama":
                url = f"{provider.base_url.rstrip('/')}/api/tags"
                with httpx.Client(timeout=15) as client:
                    response = client.get(url)
                    response.raise_for_status()
            else:
                return False, f"Unsupported provider type: {provider.provider_type}"

            return True, "Connection successful"
        except Exception as exc:
            return False, f"Connection failed: {exc}"

    def _extract_error_detail(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    message = error.get("message") or error.get("code")
                    if message:
                        return str(message)
                return str(payload)
            return str(payload)
        except Exception:
            return (response.text or "").strip() or f"HTTP {response.status_code}"
