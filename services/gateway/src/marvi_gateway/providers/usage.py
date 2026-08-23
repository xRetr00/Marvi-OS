"""Durable request accounting and provider-owned account summaries.

The ledger is the source of truth for work Marvi itself performs. It stores
only counters and dates -- never prompts, responses, model output, or keys.
Provider account APIs answer a different question (the whole account, possibly
including other applications), so their values stay explicitly labelled as
account data and never replace the local ledger.
"""

from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import paths
from .base import Usage


def _empty() -> dict[str, int]:
    return {"input": 0, "output": 0, "cached_input": 0, "reasoning": 0}


def _normalise(value: Any) -> dict[str, int]:
    raw = value if isinstance(value, dict) else {}
    return {key: max(0, int(raw.get(key, 0) or 0)) for key in _empty()}


def _public(value: dict[str, int]) -> dict[str, int]:
    usage = Usage(**_normalise(value))
    return {
        "input": usage.input,
        "output": usage.output,
        "cached_input": usage.cached_input,
        "reasoning": usage.reasoning,
        "billable": usage.billable,
    }


@dataclass
class UsageLedger:
    """Atomic JSON ledger shared by every provider call in this Gateway."""

    path: Path = field(default_factory=paths.usage_ledger)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _read(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            value = {}
        return value if isinstance(value, dict) else {}

    def _write(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, self.path)

    def record(self, provider: str, usage: Usage, at: datetime | None = None) -> None:
        if usage.total <= 0 and usage.reasoning <= 0:
            return
        day = (at or datetime.now(UTC)).astimezone(UTC).date().isoformat()
        with self._lock:
            value = self._read()
            providers = value.setdefault("providers", {})
            daily = value.setdefault("daily", {})
            for target in (
                providers.setdefault(provider, _empty()),
                daily.setdefault(day, _empty()),
            ):
                current = _normalise(target)
                current["input"] += usage.input
                current["output"] += usage.output
                current["cached_input"] += usage.cached_input
                current["reasoning"] += usage.reasoning
                target.clear()
                target.update(current)
            value["updated_at"] = datetime.now(UTC).isoformat()
            self._write(value)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            value = self._read()
        providers = {
            str(name): _public(raw)
            for name, raw in (value.get("providers") or {}).items()
            if isinstance(name, str)
        }
        daily = [
            {"date": day, **_public(raw)}
            for day, raw in sorted((value.get("daily") or {}).items())
            if isinstance(day, str)
        ]
        total = Usage()
        for raw in providers.values():
            total += Usage(
                input=raw["input"],
                output=raw["output"],
                cached_input=raw["cached_input"],
                reasoning=raw["reasoning"],
            )
        return {
            "totals": _public(total.__dict__),
            "providers": providers,
            "daily": daily,
            "updated_at": value.get("updated_at"),
        }


def collect_accounts(http: Any | None = None) -> dict[str, dict[str, Any]]:
    """Read only official account endpoints supported by configured credentials.

    Failures are data, not page failures: local request accounting remains
    available when a provider is offline or an admin credential is absent.
    """
    owns_http = http is None
    if owns_http:
        import httpx

        http = httpx.Client(timeout=6.0)

    def get(
        name: str,
        url: str,
        key_env: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        key = os.environ.get(key_env, "").strip()
        if not key:
            return None
        try:
            response = http.get(
                url,
                headers=headers or {"authorization": f"Bearer {key}"},
                params=params,
            )
            response.raise_for_status()
            body = response.json()
            return body if isinstance(body, dict) else {}
        except Exception as exc:
            return {"_error": f"{name} account API: {str(exc)[:120]}"}

    now = datetime.now(UTC)
    month = now.strftime("%Y.%m")
    start = int(datetime(now.year, now.month, 1, tzinfo=UTC).timestamp())
    anthropic_key = os.environ.get("ANTHROPIC_ADMIN_KEY", "").strip()
    # Independent vendors must not turn into serial timeout penalties. The
    # configured calls happen together and the slowest one bounds refresh.
    with ThreadPoolExecutor(max_workers=5, thread_name_prefix="usage-account") as pool:
        futures = {
            "openrouter": pool.submit(
                get, "OpenRouter", "https://openrouter.ai/api/v1/key", "OPENROUTER_API_KEY"
            ),
            "deepseek": pool.submit(
                get, "DeepSeek", "https://api.deepseek.com/user/balance", "DEEPSEEK_API_KEY"
            ),
            "deepinfra": pool.submit(
                get,
                "DeepInfra",
                "https://api.deepinfra.com/payment/usage",
                "DEEPINFRA_API_KEY",
                params={"from": month},
            ),
            "openai": pool.submit(
                get,
                "OpenAI",
                "https://api.openai.com/v1/organization/costs",
                "OPENAI_ADMIN_KEY",
                params={"start_time": start, "bucket_width": "1d", "limit": 31},
            ),
            "anthropic": pool.submit(
                get,
                "Anthropic",
                "https://api.anthropic.com/v1/organizations/cost_report",
                "ANTHROPIC_ADMIN_KEY",
                headers={
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                params={"starting_at": datetime(now.year, now.month, 1, tzinfo=UTC).isoformat()},
            ),
        }
        found = {name: future.result() for name, future in futures.items()}
    if owns_http:
        http.close()
    openrouter = found["openrouter"]
    deepseek = found["deepseek"]
    deepinfra = found["deepinfra"]
    openai = found["openai"]
    anthropic = found["anthropic"]

    result: dict[str, dict[str, Any]] = {}
    if openrouter is not None:
        data = openrouter.get("data", openrouter)
        result["openrouter"] = (
            {"state": "error", "detail": openrouter["_error"]}
            if "_error" in openrouter
            else {
                "state": "ready",
                "scope": "api_key",
                "currency": "USD",
                "spent": data.get("usage"),
                "period_spent": data.get("usage_monthly"),
                "remaining": data.get("limit_remaining"),
                "limit": data.get("limit"),
            }
        )
    if deepseek is not None:
        balances = deepseek.get("balance_infos") or []
        result["deepseek"] = (
            {"state": "error", "detail": deepseek["_error"]}
            if "_error" in deepseek
            else {
                "state": "ready",
                "scope": "account",
                "balances": [
                    {"currency": row.get("currency"), "remaining": row.get("total_balance")}
                    for row in balances
                    if isinstance(row, dict)
                ],
            }
        )
    if deepinfra is not None:
        months = deepinfra.get("months") or []
        result["deepinfra"] = (
            {"state": "error", "detail": deepinfra["_error"]}
            if "_error" in deepinfra
            else {
                "state": "ready",
                "scope": "account_month",
                "currency": "USD",
                "period_spent": sum(
                    float(row.get("total_cost", 0) or 0) for row in months if isinstance(row, dict)
                ),
            }
        )

    def bucket_cost(body: dict[str, Any] | None) -> float | None:
        if body is None or "_error" in body:
            return None
        total = 0.0
        for bucket in body.get("data") or []:
            for row in bucket.get("results") or []:
                amount = row.get("amount") or {}
                total += float(amount.get("value", 0) or 0)
        return total

    for name, body in (("openai", openai), ("anthropic", anthropic)):
        if body is None:
            continue
        result[name] = (
            {"state": "error", "detail": body["_error"]}
            if "_error" in body
            else {
                "state": "ready",
                "scope": "organization_month",
                "currency": "USD",
                "period_spent": bucket_cost(body),
            }
        )
    return result
