import { useEffect, useRef, useState } from 'react'
import { ArrowDown, ArrowUp, ChevronDown, Cloud, CloudDrizzle, CloudLightning, CloudRain, CloudSnow, LocateFixed, MapPin, Moon, Navigation, RefreshCw, Sun, Wind } from 'lucide-react'
import type { LocationState, Place, WeatherState } from '../../../shared/location'
import 'leaflet/dist/leaflet.css'
import './location-weather.css'

export function weatherLabel(code: number): string {
  if (code === 0) return 'Clear skies'
  if (code <= 3) return ['Clear skies', 'Mostly clear', 'Partly cloudy', 'Overcast'][code] ?? 'Unknown'
  if ([45, 48].includes(code)) return 'Fog'
  if (code >= 51 && code <= 57) return 'Drizzle'
  if (code >= 61 && code <= 67) return 'Rain'
  if (code >= 71 && code <= 77) return 'Snow'
  if (code >= 80 && code <= 82) return 'Rain showers'
  if (code === 85 || code === 86) return 'Snow showers'
  if (code >= 95 && code <= 99) return 'Thunderstorms'
  return 'Conditions unavailable'
}

function WeatherIcon({ code, day = true }: { code: number; day?: boolean }): React.JSX.Element {
  const Icon = code === 0 ? day ? Sun : Moon : code >= 95 ? CloudLightning
    : [71, 73, 75, 77, 85, 86].includes(code) ? CloudSnow
      : code >= 61 ? CloudRain : code >= 51 ? CloudDrizzle : Cloud
  return <Icon aria-hidden="true" />
}

export function LocationClock(): React.JSX.Element {
  const [now, setNow] = useState(() => new Date())
  const [zone, setZone] = useState<string | undefined>()
  useEffect(() => {
    let active = true
    const load = async (): Promise<void> => {
      try {
        const state = await window.marvi?.getLocation()
        if (active) setZone(state?.status === 'ready' ? state.place?.timezone : undefined)
      } catch { if (active) setZone(undefined) }
    }
    void load()
    const tick = setInterval(() => setNow(new Date()), 1000)
    const refresh = setInterval(() => void load(), 60_000)
    window.addEventListener('marvi-location-changed', load)
    return () => { active = false; clearInterval(tick); clearInterval(refresh); window.removeEventListener('marvi-location-changed', load) }
  }, [])
  return <time className="titlebar-clock" dateTime={now.toISOString()}
    title={`${now.toLocaleDateString(undefined, { timeZone: zone, dateStyle: 'full' })} · ${zone ?? 'System time'}`}>
    {now.toLocaleTimeString(undefined, { timeZone: zone, hour: '2-digit', minute: '2-digit', hour12: false })}
  </time>
}

function LocationMap({ place, expanded, stale }: { place: NonNullable<LocationState['place']>; expanded: boolean; stale: boolean }): React.JSX.Element {
  const container = useRef<HTMLDivElement>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let dispose: (() => void) | undefined
    let gone = false
    setFailed(false)
    void import('leaflet').then((L) => {
      if (gone || !container.current) return
      const map = L.map(container.current, { zoomControl: false, attributionControl: true,
        dragging: expanded, scrollWheelZoom: false, doubleClickZoom: expanded, touchZoom: expanded,
        keyboard: expanded, zoomAnimation: false, fadeAnimation: false })
        .setView([place.latitude, place.longitude], place.accuracy_m && place.accuracy_m > 5000 ? 9 : 13)
      map.attributionControl.setPrefix(false)
      const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a>',
        keepBuffer: 1, updateWhenIdle: true
      }).addTo(map)
      tiles.on('tileerror', () => { if (!gone) setFailed(true) })
      if (place.accuracy_m) L.circle([place.latitude, place.longitude], {
        radius: place.accuracy_m, color: '#147ec1', weight: 1, fillOpacity: 0.09, interactive: false
      }).addTo(map)
      L.circleMarker([place.latitude, place.longitude], { radius: 6, color: '#fafaf8', weight: 2,
        fillColor: stale ? '#72767d' : '#147ec1', fillOpacity: 1, interactive: false }).addTo(map)
      if (expanded) L.control.zoom({ position: 'topright' }).addTo(map)
      const observer = new ResizeObserver(() => map.invalidateSize({ animate: false }))
      observer.observe(container.current)
      dispose = () => { observer.disconnect(); map.remove() }
    }).catch(() => { if (!gone) setFailed(true) })
    return () => { gone = true; dispose?.() }
  }, [place.latitude, place.longitude, place.accuracy_m, expanded, stale])
  return <div className="location-map-wrap">
    <div ref={container} className="location-map" role="img" aria-label={`Map centered on ${place.label}${stale ? ', last known location' : ''}`} />
    {failed && <span className="map-unavailable">Some map tiles are unavailable · position remains marked</span>}
  </div>
}

export function LocationWeather(): React.JSX.Element {
  const [location, setLocation] = useState<LocationState | null>(null)
  const [weather, setWeather] = useState<WeatherState | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [places, setPlaces] = useState<Place[]>([])
  const [searched, setSearched] = useState(false)
  const revision = useRef(0)
  const load = async (): Promise<void> => {
    const request = ++revision.current
    try {
      const found = await window.marvi?.getLocation()
      if (request !== revision.current) return
      setLocation(found ?? null)
      if (found?.status !== 'ready') { setWeather(null); return }
      const result = await window.marvi?.getWeather()
      if (request === revision.current) setWeather(result ?? null)
    } catch { if (request === revision.current) { setLocation(null); setWeather(null) } }
  }
  useEffect(() => {
    void load()
    const timer = setInterval(() => { if (!document.hidden) void load() }, 60_000)
    return () => { revision.current++; clearInterval(timer) }
  }, [])

  const perform = async (action: () => Promise<unknown>): Promise<void> => {
    setBusy(true); setError(''); revision.current++
    try {
      const result = await action()
      if (!result) throw new Error('Gateway unavailable. Try again.')
      await load()
      window.dispatchEvent(new Event('marvi-location-changed'))
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Location update failed.') }
    finally { setBusy(false) }
  }
  const select = async (mode: 'automatic' | 'saved' | 'off', saved = location?.settings.saved ?? null): Promise<void> => {
    await perform(async () => {
      setWeather(null)
      const result = await window.marvi?.setLocation({ mode, saved })
      if (!result) return null
      setLocation(result)
      if (mode === 'automatic') return window.marvi?.refreshLocation()
      return result
    })
  }
  const data = weather?.data
  const place = location?.place
  const stateLabel = location?.settings.mode === 'saved' ? 'Saved place'
    : location?.status === 'ready' ? 'Device location' : location?.status === 'stale' ? 'Last known'
      : location?.status === 'denied' ? 'Access denied' : location?.status === 'off' ? 'Location off' : 'Unavailable'
  return <section className="location-weather" aria-label="Local weather and location">
    <article className="local-weather-card">
      <header><span>OUTSIDE</span><span>{weather?.status === 'stale' ? 'CACHED · OUT OF DATE' : 'WEATHER'}</span></header>
      {data ? <>
        <div className="weather-now"><WeatherIcon code={data.current.weather_code} day={Boolean(data.current.is_day)} />
          <div><strong>{Math.round(data.current.temperature_2m)}<small>°C</small></strong><p>{weatherLabel(data.current.weather_code)}</p></div>
          <div className="weather-context"><span>{place?.label}</span><span>Feels like {Math.round(data.current.apparent_temperature)}°</span></div>
        </div>
        <div className="weather-details"><span><Wind /> {data.current.wind_speed_10m} km/h</span><span>Humidity {data.current.relative_humidity_2m}%</span></div>
        <div className="weather-days">{data.daily.time.slice(0, 3).map((day, i) => <div key={day}>
          <span>{i === 0 ? 'Today' : new Date(`${day}T12:00:00`).toLocaleDateString(undefined, { weekday: 'short' })}</span>
          <WeatherIcon code={data.daily.weather_code[i]} />
          <span>{Math.round(data.daily.temperature_2m_max[i])}° <small>{Math.round(data.daily.temperature_2m_min[i])}°</small></span>
          <small>{data.daily.precipitation_probability_max[i] ?? '—'}% rain</small>
        </div>)}</div>
        <footer><span><ArrowUp /> {data.daily.sunrise[0]?.slice(11, 16) ?? '—'} <ArrowDown /> {data.daily.sunset[0]?.slice(11, 16) ?? '—'}</span>
          <span>{data.current.time.slice(11, 16)} · {data.timezone}</span></footer>
        <p className="weather-source">Open-Meteo · model estimate · <a href="https://open-meteo.com/" target="_blank" rel="noreferrer">Weather data</a></p>
      </> : <div className="weather-empty"><Cloud /><h3>{location?.status === 'ready' ? 'Weather unavailable' : 'A little context for your day'}</h3>
        <p>{location?.status === 'ready' ? 'The weather service is not answering. Try refreshing shortly.' : 'Choose your location to see the weather, forecast and daylight hours here.'}</p>
        <button type="button" onClick={() => location?.status === 'ready' ? void perform(loadResult) : setExpanded(true)} disabled={busy}>
          {location?.status === 'ready' ? 'Refresh weather' : 'Set location'}</button>
      </div>}
    </article>

    <article className={`local-map-card${expanded ? ' is-expanded' : ''}`}>
      <button type="button" className="map-card-heading" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
        <span><MapPin /> YOUR LOCATION</span><span><i className={location?.status === 'ready' ? 'location-dot' : 'location-dot is-muted'} />{stateLabel}<ChevronDown /></span>
      </button>
      {place ? <LocationMap place={place} expanded={expanded} stale={location?.status !== 'ready'} />
        : <button type="button" className="map-empty" onClick={() => setExpanded(true)}><Navigation /><span>{busy ? 'Finding your location…' : 'Make this your corner of the world'}</span><small>Use Windows location or save a place</small></button>}
      <div className="map-caption"><strong>{place?.label ?? 'No location selected'}</strong><span>{place ? `${Math.abs(place.latitude).toFixed(3)}° ${place.latitude >= 0 ? 'N' : 'S'} · ${Math.abs(place.longitude).toFixed(3)}° ${place.longitude >= 0 ? 'E' : 'W'}` : 'You control location access'}</span>
        {place?.accuracy_m != null && <small>Accuracy ±{Math.round(place.accuracy_m).toLocaleString()} m · {place.timestamp ? new Date(place.timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}</small>}
      </div>
      {expanded && <div className="location-controls">
        <div className="location-mode-actions"><button disabled={busy} type="button" onClick={() => void select('automatic')}><LocateFixed /> Use Windows location</button>
          <button disabled={busy || location?.settings.mode === 'off'} type="button" onClick={() => void select('off')}>Turn off</button></div>
        {location?.settings.mode === 'automatic' && <div className="location-mode-actions"><button disabled={busy} type="button" onClick={() => void perform(() => window.marvi.refreshLocation())}><RefreshCw /> Refresh location</button>
          <button type="button" onClick={() => void window.marvi?.openLocationSettings()}>Windows permissions</button></div>}
        {location?.status === 'denied' && <p>Windows location access is denied. Enable it in Windows permissions, or save a place below.</p>}
        {location?.settings.mode === 'automatic' && ['unavailable', 'timeout', 'error', 'stale'].includes(location.status) && <p>Windows could not provide a fresh position. Refresh or choose a saved place.</p>}
        <form onSubmit={(event) => { event.preventDefault(); void perform(async () => {
          const result = await window.marvi?.searchPlaces(query)
          if (!result) throw new Error('Place search unavailable. Try again or use coordinates below.')
          setPlaces(result); setSearched(true); return true
        }) }}>
          <label htmlFor="location-city">Save a city</label><div className="location-search"><input id="location-city" value={query} onChange={(event) => { setQuery(event.target.value); setSearched(false); setPlaces([]) }} maxLength={100} placeholder="City or postal code" /><button disabled={busy || query.trim().length < 2}>Search</button></div>
        </form>
        {searched && places.length === 0 && <p>No matching places. Try a nearby city.</p>}
        <div className="location-results">{places.map((candidate) => <button key={`${candidate.latitude},${candidate.longitude}`} disabled={busy} type="button" onClick={() => void select('saved', candidate)}><MapPin /><span>{candidate.label}<small>{candidate.timezone}</small></span></button>)}</div>
        {location?.settings.saved && location.settings.mode !== 'saved' && <button disabled={busy} type="button" onClick={() => void select('saved')}>Use saved place: {location.settings.saved.label}</button>}
        <details><summary>Enter coordinates</summary><form onSubmit={(event) => {
          event.preventDefault(); const fields = new FormData(event.currentTarget)
          void select('saved', { label: String(fields.get('label')), latitude: Number(fields.get('latitude')), longitude: Number(fields.get('longitude')), timezone: String(fields.get('timezone')) })
        }}><label>Place name<input name="label" required maxLength={160} placeholder="Home" /></label>
          <div className="location-coordinate-fields"><label>Latitude<input name="latitude" type="number" required min={-90} max={90} step="any" /></label><label>Longitude<input name="longitude" type="number" required min={-180} max={180} step="any" /></label></div>
          <label>Timezone<input name="timezone" required defaultValue={Intl.DateTimeFormat().resolvedOptions().timeZone} placeholder="Europe/Istanbul" /></label><button disabled={busy}>Save place</button>
        </form></details>
        <p className="location-disclosure">Weather requests share approximate coordinates with Open-Meteo. Map tiles share the viewed area with OpenStreetMap. Saved places stay on this PC; automatic positions are not stored.</p>
      </div>}
      {busy && <p className="location-feedback" role="status">Updating… Windows may ask for location permission.</p>}
      {error && <p className="location-feedback" role="alert">{error}</p>}
    </article>
  </section>

  async function loadResult(): Promise<boolean> { await load(); return true }
}
