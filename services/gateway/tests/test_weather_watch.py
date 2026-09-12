"""Weather warnings: thresholds, one warning per spell, and what is said."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from marvi_gateway import policy, voicing
from marvi_gateway.weather_watch import WeatherWatch, alerts, summary

NOW = datetime(2026, 9, 12, 13, 20)


def forecast(**rows):
    hours = 12
    base = {"precipitation_probability": [0] * hours, "precipitation": [0.0] * hours,
            "snowfall": [0.0] * hours, "weather_code": [1] * hours,
            "apparent_temperature": [20.0] * hours, "uv_index": [2.0] * hours,
            "wind_gusts_10m": [10.0] * hours}
    for name, values in rows.items():
        base[name] = values + base[name][len(values):]
    base["time"] = [f"2026-09-12T{h:02d}:00" for h in range(12, 24)]
    return {"timezone": "Europe/Istanbul", "hourly": base}


def test_quiet_forecast_warns_about_nothing():
    assert alerts(forecast(), NOW) == []


def test_rain_spell_has_start_end_intensity_and_advice():
    # 12:00 is past; the spell is 15:00-18:00 with a heavy peak.
    found = alerts(forecast(precipitation=[5, 0, 0, 1.2, 8.0, 3.0, 0], weather_code=[61, 1, 1, 61, 65, 63]), NOW)
    assert [a["kind"] for a in found] == ["rain"]
    rain = found[0]
    assert (rain["start"], rain["until"], rain["intensity"], rain["now"]) == (
        "2026-09-12T15:00", "2026-09-12T18:00", "heavy", False)
    line = voicing.spoken({"source": "weather", "kind": "rain", "payload": rain}, "Shereef")
    assert line.startswith("Shereef, from 3 PM there's heavy rain until about 6 PM.")
    assert "stay in" in line
    assert summary(rain) == "Rain 15:00-18:00 (heavy, 0%)"


def test_likely_rain_counts_but_rain_beyond_three_hours_waits():
    assert alerts(forecast(precipitation_probability=[0, 0, 70], weather_code=[1, 1, 80]), NOW)[0]["kind"] == "rain"
    assert alerts(forecast(precipitation=[0, 0, 0, 0, 0, 3.0]), NOW) == []


def test_storm_and_snow_outrank_rain_and_now_is_said_as_now():
    storm = alerts(forecast(precipitation=[0, 4.0, 4.0], weather_code=[1, 96, 61]), NOW)[0]
    assert (storm["kind"], storm["hail"], storm["now"]) == ("storm", True, True)
    assert "right now there's a thunderstorm with hail" in voicing.spoken(
        {"source": "weather", "kind": "storm", "payload": storm}, "Shereef")
    assert alerts(forecast(snowfall=[0, 0.4], weather_code=[1, 73]), NOW)[0]["kind"] == "snow"


def test_cold_heat_uv_and_wind_thresholds():
    kinds = lambda **rows: {a["kind"]: a for a in alerts(forecast(**rows), NOW)}  # noqa: E731
    assert kinds(apparent_temperature=[5, 1, 0.4]) == {}  # rounds, but 0.4 > 0
    cold = kinds(apparent_temperature=[5, -12])["cold"]
    assert cold["severe"] and "minus 12 degrees" in voicing.spoken(
        {"source": "weather", "kind": "cold", "payload": cold})
    assert not kinds(apparent_temperature=[30, 36])["hot"]["severe"]
    assert kinds(apparent_temperature=[30, 41])["hot"]["severe"]
    assert kinds(uv_index=[5, 8.2])["uv"]["value"] == 8
    assert "wind" not in kinds(wind_gusts_10m=[59])
    assert kinds(wind_gusts_10m=[20, 95])["wind"]["severe"]


def test_one_warning_per_spell_even_when_the_forecast_shifts(tmp_path):
    watch = WeatherWatch(tmp_path / "weather.json")
    first = alerts(forecast(precipitation=[0, 0, 0, 2, 2, 2]), NOW)
    assert len(watch.fresh(first)) == 1
    shifted = alerts(forecast(precipitation=[0, 0, 0, 0, 2, 2, 2]), datetime(2026, 9, 12, 13, 50))
    assert WeatherWatch(watch.path).fresh(shifted) == []  # Survives a restart, too.
    later = alerts(forecast(precipitation=[0] * 9 + [2, 2]), datetime(2026, 9, 12, 20, 5))
    assert [a["kind"] for a in watch.fresh(later)] == ["rain"]


def test_policy_speaks_weather_and_rain_cannot_be_argued_away():
    assert policy.SURFACE_CEILING["weather:hot"] == "speak"
    assert policy.must_be_said({"source": "weather", "kind": "rain"})
    assert not policy.must_be_said({"source": "weather", "kind": "uv"})


def test_initiative_journals_fresh_warnings_once(tmp_path, monkeypatch):
    from marvi_gateway import initiative as initiative_module

    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    data = forecast(precipitation=[0, 2, 2], weather_code=[1, 63, 63])
    now = datetime.now(UTC)
    data["hourly"]["time"] = [(now + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00") for i in range(12)]
    data["timezone"] = "UTC"
    appended = []

    class Journal:
        def append(self, *args, **kwargs):
            appended.append(args)

    class Weather:
        def weather(self):
            return {"status": "ready", "data": data}

        def status(self):
            return {"place": {"label": "Home"}}

    class Mind:
        settings = None
        waiting = None

    job = initiative_module.Initiative(Mind(), Journal())
    job.weather = Weather()
    first = job.run_weather()
    assert job.run_weather() == {"warned": 0}
    assert first["warned"] == len(appended) >= 1
    assert appended[0][0] == "weather" and appended[0][3]["place"] == "Home"
