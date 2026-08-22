from __future__ import annotations

from datetime import UTC, datetime

import httpx

from marvi_gateway.providers import Usage
from marvi_gateway.providers.usage import UsageLedger, collect_accounts


def test_ledger_persists_totals_and_daily_buckets(tmp_path) -> None:
    path = tmp_path / "usage.json"
    ledger = UsageLedger(path)
    ledger.record(
        "openai", Usage(input=100, output=20, cached_input=80), datetime(2026, 8, 23, tzinfo=UTC)
    )

    restored = UsageLedger(path).snapshot()

    assert restored["totals"]["billable"] == 40
    assert restored["providers"]["openai"]["cached_input"] == 80
    assert restored["daily"][0]["date"] == "2026-08-23"


def test_zero_usage_does_not_create_a_ledger(tmp_path) -> None:
    path = tmp_path / "usage.json"
    UsageLedger(path).record("openai", Usage())
    assert not path.exists()


def test_account_collectors_use_official_provider_endpoints(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "router")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek")
    monkeypatch.setenv("DEEPINFRA_API_KEY", "infra")
    seen: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path.endswith("/key"):
            return httpx.Response(
                200, json={"data": {"usage_monthly": 2.5, "limit_remaining": 7.5}}
            )
        if request.url.path.endswith("/balance"):
            return httpx.Response(
                200, json={"balance_infos": [{"currency": "USD", "total_balance": "8.00"}]}
            )
        return httpx.Response(200, json={"months": [{"total_cost": 1.25}]})

    result = collect_accounts(httpx.Client(transport=httpx.MockTransport(answer)))

    assert result["openrouter"]["period_spent"] == 2.5
    assert result["deepseek"]["balances"][0]["remaining"] == "8.00"
    assert result["deepinfra"]["period_spent"] == 1.25
    assert any("/api/v1/key" in url for url in seen)


def test_missing_admin_keys_are_not_reported_as_zero(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_ADMIN_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_ADMIN_KEY", raising=False)

    result = collect_accounts(
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    )

    assert "openai" not in result
    assert "anthropic" not in result
