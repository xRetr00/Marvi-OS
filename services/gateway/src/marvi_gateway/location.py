"""Selected place and weather. Windows acquisition belongs to Electron main.

Only the user's saved place is durable; automatic fixes and weather are bounded
in-memory snapshots. Provider strings enter model tools through the existing
untrusted-content envelope. No model tool can turn location access on.
"""
from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from . import localauth
from .paths import root
from .tools import ToolRegistry, ToolSpec
from .untrusted import wrap_external


class Place(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    label: str = Field(min_length=1, max_length=160)
    timezone: str = Field(min_length=1, max_length=80)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["off", "automatic", "saved"] = "off"
    saved: Place | None = None


class Fix(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    status: Literal["ready", "denied", "unavailable", "timeout", "error"]
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0)
    timestamp: float | None = None
    source: str = Field(default="windows", max_length=40)
    timezone: str = Field(default="UTC", max_length=80)
    generation: int = Field(ge=0)


class LocationService:
    def __init__(self, path: Path | None = None, *, weather_url: str = "https://api.open-meteo.com/v1/forecast",
                 geocoding_url: str = "https://geocoding-api.open-meteo.com/v1/search"):
        self.path = path or root() / "location.json"
        self.settings = Settings()
        try:
            self.settings = Settings.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        self.lock = threading.RLock()
        self.generation = time.time_ns()
        self.fix: Fix | None = None
        self.cached: dict[str, Any] | None = None
        self.cache_key: tuple[float, float] | None = None
        self.last_attempt = 0.0
        self.weather_url, self.geocoding_url = weather_url, geocoding_url

    def configure(self, settings: Settings) -> dict[str, Any]:
        if settings.mode == "saved" and settings.saved is None:
            raise ValueError("Choose a saved place first.")
        if settings.saved:
            ZoneInfo(settings.saved.timezone)
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(settings.model_dump_json(), encoding="utf-8")
            temporary.replace(self.path)
            self.settings = settings
            self.generation += 1
            self.fix = None
            self.cached = None
            self.cache_key = None
            self.last_attempt = 0
            return self.status()

    def report(self, fix: Fix) -> dict[str, Any]:
        with self.lock:
            # A disabled/reconfigured source cannot be revived by a late helper.
            if self.settings.mode != "automatic" or fix.generation != self.generation:
                return self.status()
            if fix.status == "ready":
                if any(value is None for value in (fix.latitude, fix.longitude, fix.accuracy_m, fix.timestamp)):
                    raise ValueError("Windows returned an incomplete position.")
                if not 0 <= time.time() - fix.timestamp < 900:
                    raise ValueError("Windows returned an expired position.")
                ZoneInfo(fix.timezone)
            self.fix = fix
            if fix.status != "ready":
                self.cached = None
            return self.status()

    def status(self) -> dict[str, Any]:
        with self.lock:
            mode = self.settings.mode
            place = None
            status = "off" if mode == "off" else "unavailable"
            if mode == "saved" and self.settings.saved:
                status = "ready"
                place = {**self.settings.saved.model_dump(), "source": "saved", "accuracy_m": None, "timestamp": None}
            elif mode == "automatic" and self.fix:
                status = self.fix.status
                if status == "ready":
                    status = "ready" if time.time() - (self.fix.timestamp or 0) < 900 else "stale"
                    place = {**self.fix.model_dump(exclude={"status", "generation"}), "label": "Device location"}
            return {"settings": self.settings.model_dump(), "generation": self.generation,
                    "status": status, "place": place}

    def local_time(self) -> dict[str, Any]:
        state = self.status()
        zone = state["place"]["timezone"] if state["place"] else None
        now = datetime.now(UTC).astimezone(ZoneInfo(zone)) if zone else datetime.now().astimezone()
        return {"datetime": now.isoformat(), "timezone": zone or now.tzname(),
                "source": "selected location" if zone else "system clock"}

    def search(self, query: str) -> list[dict[str, Any]]:
        query = query.strip()
        if not 2 <= len(query) <= 100:
            raise ValueError("Enter a city name between 2 and 100 characters.")
        with httpx.Client(timeout=8, headers={"User-Agent": "Marvi-OS/Location"}) as client:
            response = client.get(self.geocoding_url, params={"name": query, "count": 6, "language": "en", "format": "json"})
            response.raise_for_status()
            rows = response.json().get("results", [])
        places = []
        for row in rows[:6]:
            place = Place(latitude=row["latitude"], longitude=row["longitude"],
                          label=", ".join(dict.fromkeys(str(row[k]) for k in ("name", "admin1", "country") if row.get(k))),
                          timezone=row["timezone"])
            ZoneInfo(place.timezone)
            places.append(place.model_dump())
        return places

    def weather(self) -> dict[str, Any]:
        with self.lock:
            state = self.status()
            if state["status"] != "ready":
                return {"status": "unavailable", "detail": "Choose a location in Overview, or refresh Windows location.", "data": None}
            place = state["place"]
            key = (round(place["latitude"], 2), round(place["longitude"], 2))
            now = time.time()
            if key != self.cache_key:
                self.cached, self.last_attempt, self.cache_key = None, 0, key
            if self.cached and now - self.cached["fetched_at"] < 600:
                return {"status": "ready", "data": self.cached}
            if now - self.last_attempt < 60:
                return {"status": "stale" if self.cached else "unavailable", "data": self.cached,
                        "detail": "Weather provider unavailable. Retry shortly."}
            self.last_attempt = now
            try:
                with httpx.Client(timeout=8, headers={"User-Agent": "Marvi-OS/Weather"}) as client:
                    response = client.get(self.weather_url, params={
                        "latitude": key[0], "longitude": key[1], "timezone": "auto", "forecast_days": 3,
                        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day",
                        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
                    })
                    response.raise_for_status()
                    body = response.json()
                ZoneInfo(body["timezone"])
                if not isinstance(body["current"].get("temperature_2m"), (int, float)):
                    raise ValueError("Missing current temperature")
                self.cached = {"current": body["current"], "daily": body["daily"],
                               "units": body["current_units"], "timezone": body["timezone"],
                               "fetched_at": now, "source": "Open-Meteo", "kind": "model estimate"}
                # Coordinates determine the zone when available, never a fixed UTC offset.
                if self.fix and self.settings.mode == "automatic":
                    self.fix = self.fix.model_copy(update={"timezone": body["timezone"]})
                return {"status": "ready", "data": self.cached}
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                return {"status": "stale" if self.cached else "unavailable", "data": self.cached,
                        "detail": "Weather provider unavailable. Cached readings may be out of date."}


def register_location_tools(registry: ToolRegistry, service: LocationService) -> None:
    for name, description, handler in (
        ("get_location", "Read selected geographic location, coordinates, timezone, accuracy and freshness. Distinct from phone/home presence. Never invent missing location.", service.status),
        ("get_local_time", "Read current local date and time in the selected location timezone, or the system timezone if location is off.", service.local_time),
        ("get_weather", "Read current weather and three-day forecast for the selected location: temperature, rain probability, wind, sunrise and sunset. Report stale/unavailable data honestly; conditions are model estimates.", service.weather),
    ):
        registry.register(ToolSpec(name=name, description=description, arguments={}, sensitive=False,
                                  handler=lambda fn=handler: wrap_external("location-weather", fn()).model_dump()))


def location_router(service: LocationService) -> APIRouter:
    def authenticated(request: Request) -> None:
        localauth.guard(request)

    router = APIRouter(prefix="/location", dependencies=[Depends(authenticated)])

    @router.get("")
    def status() -> dict[str, Any]:
        return service.status()

    @router.put("")
    def configure(body: Settings) -> dict[str, Any]:
        try:
            return service.configure(body)
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, "Choose a valid place and timezone.") from exc

    @router.post("/fix")
    def report(body: Fix) -> dict[str, Any]:
        try:
            return service.report(body)
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, "Invalid or expired Windows location.") from exc

    @router.get("/search")
    def search(query: str) -> list[dict[str, Any]]:
        try:
            return service.search(query)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(503, "Place search unavailable. Try again or enter coordinates.") from exc

    @router.get("/weather")
    def weather() -> dict[str, Any]:
        return service.weather()

    return router
