"""Weather worth warning about, from the forecast Marvi already fetches.

`LocationService.weather()` pulls twelve hours of Open-Meteo hourly data with
the current conditions, so this costs no extra request. It reads that data,
names at most one warning per kind, and remembers until when each warning
covers -- so one rain spell is one sentence, even when the next forecast shifts
its start by an hour. The mind decides whether and how loudly to say it.

Thresholds, and where they come from:

    rain   >= 0.5 mm/h, or >= 60% chance on a rain code, starting within 3h.
           Peak intensity per the AMS scale: light < 2.5, heavy >= 7.6 mm/h.
    snow   any snowfall or snow code inside that same precipitation spell.
    storm  thunderstorm codes 95-99 (96/99 with hail) inside that spell.
    cold   feels-like <= 0 C within 6h; <= -10 C is frostbite territory.
    hot    feels-like >= 35 C within 6h; >= 40 C is dangerous heat (NWS).
    uv     UV index >= 8 within 6h (WHO "very high"); >= 11 is extreme.
    wind   gusts >= 60 km/h within 6h; >= 90 km/h damages things.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

WET_MM, WET_CHANCE, LIGHT_MM, HEAVY_MM = 0.5, 60, 2.5, 7.6
COLD_C, FREEZING_C, HOT_C, SCORCHING_C = 0, -10, 35, 40
UV_HIGH, UV_EXTREME, GUST_KMH, DAMAGING_KMH = 8, 11, 60, 90
PRECIP_LEAD_HOURS, OTHER_LEAD_HOURS = 3, 6
SNOW_CODES = {71, 73, 75, 77, 85, 86}


def _value(rows: dict[str, list[Any]], name: str, i: int) -> float:
    values = rows.get(name) or []
    value = values[i] if i < len(values) else None
    return float(value) if value is not None else 0.0


def _wet(rows: dict[str, list[Any]], i: int) -> bool:
    code = int(_value(rows, "weather_code", i))
    return (_value(rows, "precipitation", i) >= WET_MM
            or _value(rows, "snowfall", i) > 0
            or (_value(rows, "precipitation_probability", i) >= WET_CHANCE and code >= 51))


def alerts(data: dict[str, Any], now: datetime | None = None) -> list[dict[str, Any]]:
    """Every warning the forecast supports right now, soonest first."""
    rows = data.get("hourly") or {}
    times = [str(t) for t in rows.get("time") or []]
    local = (now or datetime.now(ZoneInfo(data["timezone"]))).strftime("%Y-%m-%dT%H")
    hours = [i for i, t in enumerate(times) if t[:13] >= local]
    if not hours:
        return []
    found: list[dict[str, Any]] = []

    # One precipitation spell: the first wet hour inside the lead window,
    # carried through every consecutive wet hour after it.
    start = next((i for i in hours[:PRECIP_LEAD_HOURS + 1] if _wet(rows, i)), None)
    if start is not None:
        spell = [start]
        while spell[-1] + 1 in hours and _wet(rows, spell[-1] + 1):
            spell.append(spell[-1] + 1)
        codes = {int(_value(rows, "weather_code", i)) for i in spell}
        peak = max(_value(rows, "precipitation", i) for i in spell)
        kind = ("storm" if max(codes) >= 95
                else "snow" if codes & SNOW_CODES or any(_value(rows, "snowfall", i) > 0 for i in spell)
                else "rain")
        found.append({
            "kind": kind, "start": times[start], "until": _after(times, spell[-1]),
            "open_ended": spell[-1] == hours[-1], "now": start == hours[0],
            "hours": len(spell), "peak_mm": round(peak, 1),
            "chance": round(max(_value(rows, "precipitation_probability", i) for i in spell)),
            "intensity": "heavy" if peak >= HEAVY_MM else "light" if peak < LIGHT_MM else "moderate",
            "hail": bool(codes & {96, 99}),
        })

    ahead = hours[:OTHER_LEAD_HOURS + 1]
    day_end = f"{times[hours[0]][:10]}T23:59"
    for kind, name, pick, hit, severe in (
        ("cold", "apparent_temperature", min, lambda v: v <= COLD_C, lambda v: v <= FREEZING_C),
        ("hot", "apparent_temperature", max, lambda v: v >= HOT_C, lambda v: v >= SCORCHING_C),
        ("uv", "uv_index", max, lambda v: v >= UV_HIGH, lambda v: v >= UV_EXTREME),
        ("wind", "wind_gusts_10m", max, lambda v: v >= GUST_KMH, lambda v: v >= DAMAGING_KMH),
    ):
        if not rows.get(name):
            continue
        at = pick(ahead, key=lambda i, n=name: _value(rows, n, i))
        value = _value(rows, name, at)
        if hit(value):
            found.append({"kind": kind, "start": times[at], "until": day_end,
                          "value": round(value), "severe": bool(severe(value)),
                          "now": at == hours[0]})
    return found


def _after(times: list[str], i: int) -> str:
    """The hour a spell ends: the start of the first dry hour after it."""
    if i + 1 < len(times):
        return times[i + 1]
    return f"{times[i][:11]}{int(times[i][11:13]) + 1:02d}:00" if times[i][11:13] < "23" else times[i]


def summary(alert: dict[str, Any]) -> str:
    """The journal line. `voicing` writes what is actually said."""
    kind, start = alert["kind"], alert["start"][11:16]
    if kind in ("rain", "snow", "storm"):
        return (f"{kind.capitalize()} {start}-{alert['until'][11:16]}"
                f" ({alert['intensity']}, {alert['chance']}%)")
    unit = {"cold": " C feels-like", "hot": " C feels-like", "uv": " UV", "wind": " km/h gusts"}[kind]
    return f"Weather {kind}: {alert['value']}{unit} at {start}"


class WeatherWatch:
    """Remembers, per kind, until when the last warning covered."""

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            self.covered: dict[str, str] = dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            self.covered = {}

    def fresh(self, found: list[dict[str, Any]]) -> list[dict[str, Any]]:
        new = []
        for alert in found:
            # ISO local times compare correctly as strings.
            if alert["start"] < self.covered.get(alert["kind"], ""):
                continue
            self.covered[alert["kind"]] = alert["until"]
            new.append(alert)
        if new:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.covered), encoding="utf-8")
        return new
