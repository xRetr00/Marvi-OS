"""Selected place and weather. Windows acquisition belongs to Electron main.

Only the user's saved place is durable; automatic fixes and weather are bounded
in-memory snapshots. Provider strings enter model tools through the existing
untrusted-content envelope. No model tool can turn location access on.
"""
from __future__ import annotations

import contextlib
import math
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    # On by default: Windows location, falling back to the user's pins. Off is
    # one click away and is remembered.
    mode: Literal["off", "automatic", "saved"] = "automatic"
    #: The active place in `saved` mode, and the preferred pin when an
    #: internet-provider fix cannot tell two nearby pins apart.
    saved: Place | None = None
    #: Named pins -- Home, Work -- that automatic fixes snap to.
    places: list[Place] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def valid_place(self) -> Settings:
        if self.mode == "saved" and self.saved is None:
            raise ValueError("Choose a saved place first.")
        for place in (self.saved, *self.places):
            if place:
                try:
                    ZoneInfo(place.timezone)
                except (KeyError, ValueError) as exc:
                    raise ValueError("Unknown timezone") from exc
        return self


#: How far a pin may be from a fix and still be where you are. An internet
#: provider fix only knows the city, so it matches any pin in town and prefers
#: `saved`; a Wi-Fi/GPS fix must be close.
COARSE_FIX_M, COARSE_MATCH_M, PRECISE_MATCH_M = 1000, 25_000, 150


def _meters(a: Any, b: Any) -> float:
    """Equirectangular distance; exact enough below 50 km."""
    x = math.radians(b.longitude - a.longitude) * math.cos(math.radians((a.latitude + b.latitude) / 2))
    return 6_371_000 * math.hypot(x, math.radians(b.latitude - a.latitude))


def _photon_label(props: dict[str, Any]) -> str:
    street = " ".join(str(props[k]) for k in ("street", "housenumber") if props.get(k))
    parts = [props.get("name"), street, props.get("district"), props.get("city") or props.get("state"),
             props.get("country")]
    return ", ".join(dict.fromkeys(str(p) for p in parts if p))[:160] or "Pinned place"


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
                 geocoding_url: str = "https://photon.komoot.io"):
        self.path = path or root() / "location.json"
        self.settings = Settings()
        with contextlib.suppress(OSError, ValueError):
            self.settings = Settings.model_validate_json(self.path.read_text(encoding="utf-8"))
        self.lock = threading.RLock()
        self.generation = int(time.time() * 1000)  # Exact in JavaScript numbers, too.
        self.fix: Fix | None = None
        self.cached: dict[str, Any] | None = None
        self.cache_key: tuple[float, float] | None = None
        self.last_attempt = 0.0
        #: The zone Open-Meteo resolved for the active coordinates; beats a
        #: pin's guessed zone for a place searched in another country.
        self.zone: str | None = None
        #: Reverse-geocoded labels by rounded coordinates. Photon is asked once
        #: per ~100 m moved, never on a timer.
        self.labels: dict[tuple[float, float, bool], str] = {}
        self.weather_url, self.geocoding_url = weather_url, geocoding_url.rstrip("/")

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
            # Pins and their order are not a new source: keep a live fix so
            # adding "Work" does not throw away where Windows says you are.
            same_source = (settings.mode == self.settings.mode == "automatic")
            self.settings = settings
            if not same_source:
                self.generation += 1
                self.fix = None
                self.cached = None
                self.cache_key = None
                self.last_attempt = 0
            self.zone = None
            return self.status()

    def report(self, fix: Fix) -> dict[str, Any]:
        # A disabled/reconfigured source cannot be revived by a late helper.
        late = lambda: self.settings.mode != "automatic" or fix.generation != self.generation  # noqa: E731
        with self.lock:
            if late():
                return self.status()
        if fix.status == "ready":
            if any(value is None for value in (fix.latitude, fix.longitude, fix.accuracy_m, fix.timestamp)):
                raise ValueError("Windows returned an incomplete position.")
            if not 0 <= time.time() - fix.timestamp < 900:
                raise ValueError("Windows returned an expired position.")
            ZoneInfo(fix.timezone)
            # Named before it is published, so nobody reads "Device location"
            # in the half second the lookup takes. Network stays outside the lock.
            self._label_fix(fix)
        with self.lock:
            if late():
                return self.status()
            self.fix = fix
            if fix.status != "ready":
                self.cached = None
            return self.status()

    def _coarse(self, fix: Fix) -> bool:
        return (fix.accuracy_m or 0) > COARSE_FIX_M or "IP" in fix.source

    def _pin_for(self, fix: Fix) -> Place | None:
        """The pin you are at, if the fix supports one."""
        coarse = self._coarse(fix)
        reach = max(fix.accuracy_m or 0, COARSE_MATCH_M if coarse else PRECISE_MATCH_M)
        near = [p for p in self.settings.places if _meters(p, fix) <= reach]
        if coarse and self.settings.saved in near:
            return self.settings.saved  # ponytail: an IP fix cannot tell Home from Work; `saved` is the tiebreak
        return min(near, key=lambda p: _meters(p, fix), default=None)

    def _label_fix(self, fix: Fix) -> None:
        """A real place name for an unpinned fix: the street, or "Near <city>"."""
        coarse = self._coarse(fix)
        key = (round(fix.latitude or 0, 3), round(fix.longitude or 0, 3), coarse)
        if key in self.labels or self._pin_for(fix):
            return
        with contextlib.suppress(httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
            props = self._photon("/reverse", {"lat": fix.latitude, "lon": fix.longitude, "limit": 1})[0]["properties"]
            town = props.get("city") or props.get("county") or props.get("state")
            label = f"Near {town}" if coarse and town else _photon_label(props)
            with self.lock:
                if len(self.labels) > 32:
                    self.labels.clear()
                self.labels[key] = label

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
                    fix = self.fix
                    if pin := self._pin_for(fix):
                        # The pin is exact; the fix only chose it.
                        place = {**pin.model_dump(), "source": f"Pin, matched by {fix.source}",
                                 "accuracy_m": None, "timestamp": fix.timestamp, "pinned": True}
                    else:
                        key = (round(fix.latitude or 0, 3), round(fix.longitude or 0, 3), self._coarse(fix))
                        place = {**fix.model_dump(exclude={"status", "generation"}),
                                 "label": self.labels.get(key, "Device location"), "coarse": self._coarse(fix)}
            if place and self.zone:
                place["timezone"] = self.zone
            return {"settings": self.settings.model_dump(), "generation": self.generation,
                    "status": status, "place": place}

    def local_time(self) -> dict[str, Any]:
        state = self.status()
        zone = state["place"]["timezone"] if state["status"] == "ready" else None
        now = datetime.now(UTC).astimezone(ZoneInfo(zone)) if zone else datetime.now().astimezone()
        return {"datetime": now.isoformat(), "timezone": zone or now.tzname(),
                "source": "selected location" if zone else "system clock"}

    def _photon(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        # Photon (komoot, OpenStreetMap data): streets, addresses and places,
        # not only cities. User-triggered or once per move; never polled.
        with httpx.Client(timeout=8, headers={"User-Agent": "Marvi-OS/Location"}) as client:
            response = client.get(f"{self.geocoding_url}{path}", params={**params, "lang": "en"})
            response.raise_for_status()
            return list(response.json().get("features", []))

    def search(self, query: str, timezone: str = "UTC") -> list[dict[str, Any]]:
        query = query.strip()
        if not 2 <= len(query) <= 100:
            raise ValueError("Enter a place, street or address between 2 and 100 characters.")
        ZoneInfo(timezone)
        params: dict[str, Any] = {"q": query, "limit": 8}
        with self.lock:
            here = self.status()["place"]
        if here:
            # Nearby results first: "Migros" means the one down the road.
            params.update(lat=here["latitude"], lon=here["longitude"])
            timezone = here["timezone"]
        places = []
        for feature in self._photon("/api/", params)[:8]:
            lon, lat = feature["geometry"]["coordinates"][:2]
            props = feature.get("properties") or {}
            place = Place(latitude=lat, longitude=lon, label=_photon_label(props), timezone=timezone)
            if any(row["label"] == place.label for row in places):
                continue  # One shop mapped twice (node + building) is one answer.
            kind = str(props.get("osm_value") or props.get("type") or "").replace("_", " ")[:40]
            places.append({**place.model_dump(), "kind": kind})
        return places

    def reverse(self, latitude: float, longitude: float) -> dict[str, Any]:
        """The address at a dropped pin, to name it before saving."""
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError("Coordinates out of range.")
        rows = self._photon("/reverse", {"lat": latitude, "lon": longitude, "limit": 1})
        return {"label": _photon_label(rows[0].get("properties") or {}) if rows else ""}

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
                        "forecast_hours": 12,
                        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day",
                        "hourly": "precipitation_probability,precipitation,snowfall,weather_code,apparent_temperature,uv_index,wind_gusts_10m",
                        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
                    })
                    response.raise_for_status()
                    body = response.json()
                ZoneInfo(body["timezone"])
                body = Forecast.model_validate(body).model_dump()
                self.cached = {"current": body["current"], "daily": body["daily"], "hourly": body["hourly"],
                               "units": body["current_units"], "timezone": body["timezone"],
                               "fetched_at": now, "source": "Open-Meteo", "kind": "model estimate"}
                # Coordinates determine the zone when available, never a fixed UTC offset.
                if self.fix and self.settings.mode == "automatic":
                    self.fix = self.fix.model_copy(update={"timezone": body["timezone"]})
                self.zone = body["timezone"]
                return {"status": "ready", "data": self.cached}
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                return {"status": "stale" if self.cached else "unavailable", "data": self.cached,
                        "detail": "Weather provider unavailable. Cached readings may be out of date."}

    def tool_location(self) -> dict[str, Any]:
        state = self.status()
        return {"status": state["status"], "place": state["place"]}

    def tool_weather(self) -> str:
        result = self.weather()
        data = result.get("data")
        if not data:
            return result["detail"]
        place = self.status()["place"]
        current, daily = data["current"], data["daily"]
        lines = [f"{result['status'].upper()} weather for {place['label'] if place else 'previous location'}; Open-Meteo model estimate.",
                 f"Weather valid at {current['time']} {data['timezone']}; retrieved {datetime.fromtimestamp(data['fetched_at'], UTC).isoformat()}.",
                 f"Temperature {current['temperature_2m']} C, feels {current['apparent_temperature']} C; humidity {current['relative_humidity_2m']}%; wind {current['wind_speed_10m']} km/h; WMO weather code {current['weather_code']}."]
        for i, day in enumerate(daily["time"]):
            lines.append(f"{day}: {daily['temperature_2m_min'][i]}..{daily['temperature_2m_max'][i]} C, rain {daily['precipitation_probability_max'][i]}%, WMO {daily['weather_code'][i]}.")
        lines.append(f"Sunrise {daily['sunrise'][0]}; sunset {daily['sunset'][0]}.")
        from .weather_watch import alerts, summary

        if warnings := [summary(a) for a in alerts(data)]:
            lines.append("Next hours: " + "; ".join(warnings) + ".")
        return "\n".join(lines)


class CurrentWeather(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    time: str
    temperature_2m: float
    apparent_temperature: float
    relative_humidity_2m: float = Field(ge=0, le=100)
    weather_code: int = Field(ge=0, le=99)
    wind_speed_10m: float = Field(ge=0)
    is_day: Literal[0, 1]


class DailyWeather(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    time: list[str] = Field(min_length=1, max_length=3)
    weather_code: list[int | None]
    temperature_2m_max: list[float | None]
    temperature_2m_min: list[float | None]
    precipitation_probability_max: list[float | None]
    sunrise: list[str | None]
    sunset: list[str | None]

    @model_validator(mode="after")
    def matching_days(self) -> DailyWeather:
        if any(len(values) != len(self.time) for values in self.model_dump().values()):
            raise ValueError("Incomplete forecast")
        return self


class HourlyWeather(BaseModel):
    """The next twelve hours, for `weather_watch`. Gaps are allowed, not guessed."""
    model_config = ConfigDict(allow_inf_nan=False)
    time: list[str] = Field(default_factory=list, max_length=48)
    precipitation_probability: list[float | None] = Field(default_factory=list)
    precipitation: list[float | None] = Field(default_factory=list)
    snowfall: list[float | None] = Field(default_factory=list)
    weather_code: list[int | None] = Field(default_factory=list)
    apparent_temperature: list[float | None] = Field(default_factory=list)
    uv_index: list[float | None] = Field(default_factory=list)
    wind_gusts_10m: list[float | None] = Field(default_factory=list)


class Forecast(BaseModel):
    current: CurrentWeather
    daily: DailyWeather
    hourly: HourlyWeather = Field(default_factory=HourlyWeather)
    timezone: str
    current_units: dict[str, str]


def register_location_tools(registry: ToolRegistry, service: LocationService) -> None:
    for name, description, handler in (
        ("get_location", "Read selected geographic location, coordinates, timezone, accuracy and freshness. Distinct from phone/home presence. Never invent missing location.", service.tool_location),
        ("get_local_time", "Read current local date and time in the selected location timezone, or the system timezone if location is off.", service.local_time),
        ("get_weather", "Read current weather and three-day forecast for the selected location: temperature, rain probability, wind, sunrise and sunset. Report stale/unavailable data honestly; conditions are model estimates.", service.tool_weather),
    ):
        registry.register(ToolSpec(name=name, description=description, arguments={}, sensitive=False,
                                  handler=lambda fn=handler: wrap_external("location-weather", fn()).model_dump()))


def location_router(service: LocationService, audit: Callable[..., Any] = lambda *args: None) -> APIRouter:
    def authenticated(request: Request) -> None:
        localauth.guard(request)

    router = APIRouter(prefix="/location", dependencies=[Depends(authenticated)])

    @router.get("")
    def status() -> dict[str, Any]:
        return service.status()

    @router.put("")
    def configure(body: Settings) -> dict[str, Any]:
        try:
            result = service.configure(body)
            audit("location", "settings", {"mode": body.mode})
            return result
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, "Choose a valid place and timezone.") from exc

    @router.post("/fix")
    def report(body: Fix) -> dict[str, Any]:
        try:
            return service.report(body)
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, "Invalid or expired Windows location.") from exc

    @router.get("/search")
    def search(query: str, timezone: str = "UTC") -> list[dict[str, Any]]:
        try:
            return service.search(query, timezone)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as exc:
            raise HTTPException(503, "Place search unavailable. Try again or drop a pin on the map.") from exc

    @router.get("/reverse")
    def reverse(latitude: float, longitude: float) -> dict[str, Any]:
        try:
            return service.reverse(latitude, longitude)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(503, "Address lookup unavailable. Name the pin yourself.") from exc

    @router.get("/weather")
    def weather() -> dict[str, Any]:
        return service.weather()

    return router
