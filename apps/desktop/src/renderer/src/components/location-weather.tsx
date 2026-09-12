import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  Cloud,
  CloudSun,
  CloudMoon,
  CloudDrizzle,
  CloudLightning,
  CloudRain,
  CloudSnow,
  LocateFixed,
  MapPin,
  Moon,
  Navigation,
  RefreshCw,
  Sun,
  Wind
} from 'lucide-react'
import type {
  LocationSettings,
  LocationState,
  Place,
  SearchResult,
  WeatherState
} from '../../../shared/location'
import { weatherLabel } from '../../../shared/weather'
import 'leaflet/dist/leaflet.css'
import './location-weather.css'

function WeatherIcon({ code, day = true }: { code: number; day?: boolean }): React.JSX.Element {
  const Icon =
    code === 0 || code === 1
      ? day
        ? Sun
        : Moon
      : code === 2
        ? day
          ? CloudSun
          : CloudMoon
        : code >= 95
          ? CloudLightning
          : [71, 73, 75, 77, 85, 86].includes(code)
            ? CloudSnow
            : code >= 61
              ? CloudRain
              : code >= 51
                ? CloudDrizzle
                : Cloud
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
      } catch {
        if (active) setZone(undefined)
      }
    }
    void load()
    const tick = setInterval(() => setNow(new Date()), 1000)
    const refresh = setInterval(() => void load(), 60_000)
    window.addEventListener('marvi-location-changed', load)
    return () => {
      active = false
      clearInterval(tick)
      clearInterval(refresh)
      window.removeEventListener('marvi-location-changed', load)
    }
  }, [])
  return (
    <time
      className="titlebar-clock"
      dateTime={now.toISOString()}
      title={`${now.toLocaleDateString(undefined, { timeZone: zone, dateStyle: 'full' })} · ${zone ?? 'System time'}`}
    >
      {now.toLocaleTimeString(undefined, {
        timeZone: zone,
        hour: '2-digit',
        minute: '2-digit',
        hour12: false
      })}
    </time>
  )
}

type Leaflet = typeof import('leaflet')
type CurrentPlace = NonNullable<LocationState['place']>
export interface Draft {
  latitude: number
  longitude: number
  name: string
  address: string
}

const same = (a: Place, b: Place | null | undefined): boolean =>
  !!b && a.latitude === b.latitude && a.longitude === b.longitude && a.label === b.label

/** Street level for an exact spot; city level for an internet-provider fix. */
function zoomFor(place: CurrentPlace): number {
  if (place.accuracy_m == null) return 16
  return place.accuracy_m > 5000 ? 11 : place.accuracy_m > 1000 ? 13 : 16
}

function LocationMap({
  place,
  pins,
  draft,
  focus,
  expanded,
  stale,
  onPick
}: {
  place: CurrentPlace | null | undefined
  pins: Place[]
  draft: Draft | null
  focus: { latitude: number; longitude: number; n: number } | null
  expanded: boolean
  stale: boolean
  onPick: (latitude: number, longitude: number) => void
}): React.JSX.Element {
  const container = useRef<HTMLDivElement>(null)
  const [failed, setFailed] = useState(false)
  const [ready, setReady] = useState<{ L: Leaflet; map: import('leaflet').Map } | null>(null)
  const pick = useRef(onPick)
  useEffect(() => {
    pick.current = onPick
  }, [onPick])
  // One map per mode. Layers below update in place, so saving a pin or a new
  // fix never throws away where the user has panned to.
  useEffect(() => {
    let dispose: (() => void) | undefined
    let gone = false
    void import('leaflet')
      .then((L) => {
        if (gone || !container.current) return
        setFailed(false)
        const map = L.map(container.current, {
          zoomControl: false,
          attributionControl: false,
          dragging: expanded,
          scrollWheelZoom: expanded,
          doubleClickZoom: expanded,
          touchZoom: expanded,
          boxZoom: expanded,
          keyboard: expanded,
          zoomAnimation: expanded,
          fadeAnimation: false
        }).setView([20, 0], 2)
        const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
          maxZoom: 19,
          attribution:
            '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a>',
          keepBuffer: 1,
          updateWhenIdle: true
        }).addTo(map)
        tiles.on('tileerror', () => {
          if (!gone) setFailed(true)
        })
        if (expanded) {
          L.control.zoom({ position: 'topright' }).addTo(map)
          L.control.scale({ imperial: false, position: 'bottomleft' }).addTo(map)
          map.on('click', (event) => pick.current(event.latlng.lat, event.latlng.lng))
        }
        const observer = new ResizeObserver(() => map.invalidateSize({ animate: false }))
        observer.observe(container.current)
        setReady({ L, map })
        dispose = () => {
          observer.disconnect()
          map.remove()
        }
      })
      .catch(() => {
        if (!gone) setFailed(true)
      })
    return () => {
      gone = true
      setReady(null)
      dispose?.()
    }
  }, [expanded])

  const lat = place?.latitude
  const lon = place?.longitude
  const accuracy = place?.accuracy_m ?? null
  const zoom = place ? zoomFor(place) : 2
  const pinLat = pins[0]?.latitude
  const pinLon = pins[0]?.longitude
  // Recentre only when the position itself moves, never on a routine poll.
  useEffect(() => {
    if (!ready) return
    if (lat != null && lon != null) ready.map.setView([lat, lon], zoom, { animate: false })
    else if (pinLat != null && pinLon != null) ready.map.setView([pinLat, pinLon], 15)
  }, [ready, lat, lon, zoom, pinLat, pinLon])

  useEffect(() => {
    if (!ready || lat == null || lon == null) return
    const { L, map } = ready
    const layer = L.layerGroup().addTo(map)
    if (accuracy)
      L.circle([lat, lon], {
        radius: accuracy,
        color: '#147ec1',
        weight: 1,
        fillOpacity: 0.07,
        interactive: false
      }).addTo(layer)
    L.circleMarker([lat, lon], {
      radius: 6,
      color: '#fafaf8',
      weight: 2,
      fillColor: stale ? '#72767d' : '#147ec1',
      fillOpacity: 1,
      interactive: false
    }).addTo(layer)
    return () => void layer.remove()
  }, [ready, lat, lon, accuracy, stale])

  const pinKey = JSON.stringify(pins)
  useEffect(() => {
    if (!ready) return
    const { L, map } = ready
    const layer = L.layerGroup().addTo(map)
    for (const pin of JSON.parse(pinKey) as Place[])
      L.marker([pin.latitude, pin.longitude], {
        icon: L.divIcon({ className: 'map-pin', iconSize: [14, 14] }),
        keyboard: false,
        title: pin.label
      })
        .bindTooltip(pin.label.split(',')[0], {
          permanent: expanded,
          direction: 'top',
          offset: [0, -8],
          className: 'map-pin-label'
        })
        .addTo(layer)
    return () => void layer.remove()
  }, [ready, pinKey, expanded])

  const draftLat = draft?.latitude
  const draftLon = draft?.longitude
  useEffect(() => {
    if (!ready || draftLat == null || draftLon == null) return
    const { L, map } = ready
    const marker = L.marker([draftLat, draftLon], {
      icon: L.divIcon({ className: 'map-pin is-draft', iconSize: [20, 20] }),
      draggable: true,
      autoPan: true,
      title: 'New pin: drag to adjust'
    }).addTo(map)
    marker.on('dragend', () => {
      const at = marker.getLatLng()
      pick.current(at.lat, at.lng)
    })
    if (!map.getBounds().pad(-0.1).contains([draftLat, draftLon]))
      map.setView([draftLat, draftLon], Math.max(map.getZoom(), 16))
    return () => void marker.remove()
  }, [ready, draftLat, draftLon])

  useEffect(() => {
    if (ready && focus) ready.map.setView([focus.latitude, focus.longitude], 17)
  }, [ready, focus])

  return (
    <div className="location-map-wrap">
      <div
        ref={container}
        className="location-map"
        role={expanded ? 'region' : 'img'}
        aria-label={
          place
            ? `Map centered on ${place.label}${stale ? ', last known location' : ''}`
            : 'Map. Click to drop a pin.'
        }
      />
      {expanded && !draft && <span className="map-hint">Click the map to drop a pin</span>}
      {failed && (
        <span className="map-unavailable">
          Some map tiles are unavailable · position remains marked
        </span>
      )}
    </div>
  )
}

export function LocationWeather(): React.JSX.Element {
  const [location, setLocation] = useState<LocationState | null>(null)
  const [weather, setWeather] = useState<WeatherState | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [places, setPlaces] = useState<SearchResult[]>([])
  const [searched, setSearched] = useState(false)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [focus, setFocus] = useState<{ latitude: number; longitude: number; n: number } | null>(
    null
  )
  const revision = useRef(0)
  const lookup = useRef(0)
  const load = useCallback(async (): Promise<void> => {
    const request = ++revision.current
    try {
      const found = await window.marvi?.getLocation()
      if (request !== revision.current) return
      setLocation(found ?? null)
      if (found?.status !== 'ready') {
        setWeather(null)
        return
      }
      const result = await window.marvi?.getWeather()
      if (request === revision.current) setWeather(result ?? null)
    } catch {
      if (request === revision.current) {
        setLocation(null)
        setWeather(null)
      }
    }
  }, [])
  useEffect(() => {
    const initial = setTimeout(() => void load(), 0)
    const timer = setInterval(() => {
      if (!document.hidden) void load()
    }, 60_000)
    return () => {
      // Invalidate pending network results, not a DOM ref snapshot.
      // eslint-disable-next-line react-hooks/exhaustive-deps
      revision.current++
      clearTimeout(initial)
      clearInterval(timer)
    }
  }, [load])

  const perform = async (action: () => Promise<unknown>): Promise<boolean> => {
    setBusy(true)
    setError('')
    revision.current++
    try {
      const result = await action()
      if (!result) throw new Error('Gateway unavailable. Try again.')
      await load()
      window.dispatchEvent(new Event('marvi-location-changed'))
      return true
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Location update failed.')
      return false
    } finally {
      setBusy(false)
    }
  }
  const configure = (patch: Partial<LocationSettings>): Promise<boolean> => {
    const current = location?.settings
    const next: LocationSettings = {
      mode: current?.mode ?? 'automatic',
      saved: current?.saved ?? null,
      places: current?.places ?? [],
      ...patch
    }
    return perform(async () => {
      if (patch.mode) setWeather(null)
      const result = await window.marvi?.setLocation(next)
      if (!result) return null
      setLocation(result)
      if (patch.mode === 'automatic') return window.marvi?.refreshLocation()
      return result
    })
  }
  // A dropped or dragged pin: name it from the address underneath.
  const pick = useCallback((latitude: number, longitude: number): void => {
    const request = ++lookup.current
    setDraft((old) => ({ latitude, longitude, name: old?.name ?? '', address: '' }))
    const named = (label: string): void => {
      if (request === lookup.current) setDraft((old) => old && { ...old, address: label })
    }
    void window.marvi
      ?.reversePlace(latitude, longitude)
      .then((found) => named(found?.label || 'Address unavailable'))
      .catch(() => named('Address unavailable'))
  }, [])
  const savePin = async (): Promise<void> => {
    if (!draft) return
    const settings = location?.settings
    const pin: Place = {
      latitude: Number(draft.latitude.toFixed(6)),
      longitude: Number(draft.longitude.toFixed(6)),
      label: (draft.name.trim() || draft.address || 'Pinned place').slice(0, 160),
      timezone: place?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone
    }
    const kept = (settings?.places ?? []).filter((p) => p.label !== pin.label)
    const main = settings?.saved
    const saved = !main || main.label === pin.label ? pin : main
    if (await configure({ places: [...kept, pin], saved })) setDraft(null)
  }
  const removePin = (pin: Place): void => {
    const settings = location?.settings
    const main = same(pin, settings?.saved)
    void configure({
      places: (settings?.places ?? []).filter((p) => !same(pin, p)),
      saved: main ? null : (settings?.saved ?? null),
      ...(main && settings?.mode === 'saved' ? { mode: 'automatic' as const } : {})
    })
  }
  const data = weather?.data
  const place = location?.place
  const pins = location?.settings.places ?? []
  const stateLabel =
    location?.settings.mode === 'saved'
      ? 'Saved place'
      : place?.pinned && location?.status === 'ready'
        ? place.label.split(',')[0]
        : place?.coarse && location?.status === 'ready'
          ? 'Approximate'
          : location?.status === 'ready'
            ? 'Device location'
            : location?.status === 'stale'
              ? 'Last known'
              : location?.status === 'denied'
                ? 'Access denied'
                : location?.status === 'off'
                  ? 'Location off'
                  : 'Unavailable'
  return (
    <section className="location-weather" aria-label="Local weather and location">
      <article className="local-weather-card">
        <header>
          <span>OUTSIDE</span>
          <span>{weather?.status === 'stale' ? 'CACHED · OUT OF DATE' : 'WEATHER'}</span>
        </header>
        {data ? (
          <>
            <div className="weather-now">
              <WeatherIcon code={data.current.weather_code} day={Boolean(data.current.is_day)} />
              <div>
                <strong>
                  {Math.round(data.current.temperature_2m)}
                  <small>°C</small>
                </strong>
                <p>{weatherLabel(data.current.weather_code)}</p>
              </div>
              <div className="weather-context">
                <span>{place?.label}</span>
                <span>Feels like {Math.round(data.current.apparent_temperature)}°</span>
              </div>
            </div>
            <div className="weather-details">
              <span>
                <Wind /> {data.current.wind_speed_10m} km/h
              </span>
              <span>Humidity {data.current.relative_humidity_2m}%</span>
            </div>
            <div className="weather-days">
              {data.daily.time.slice(0, 3).map((day, i) => (
                <div key={day}>
                  <span>
                    {i === 0
                      ? 'Today'
                      : new Date(`${day}T12:00:00`).toLocaleDateString(undefined, {
                          weekday: 'short'
                        })}
                  </span>
                  <WeatherIcon code={data.daily.weather_code[i] ?? -1} />
                  <span>
                    {data.daily.temperature_2m_max[i] == null
                      ? '—'
                      : Math.round(data.daily.temperature_2m_max[i])}
                    °{' '}
                    <small>
                      {data.daily.temperature_2m_min[i] == null
                        ? '—'
                        : Math.round(data.daily.temperature_2m_min[i])}
                      °
                    </small>
                  </span>
                  <small>{data.daily.precipitation_probability_max[i] ?? '—'}% rain</small>
                </div>
              ))}
            </div>
            <footer>
              <span>
                <ArrowUp /> {data.daily.sunrise[0]?.slice(11, 16) ?? '—'} <ArrowDown />{' '}
                {data.daily.sunset[0]?.slice(11, 16) ?? '—'}
              </span>
              <span>
                {data.current.time.slice(11, 16)} · {data.timezone}
              </span>
            </footer>
            <p className="weather-source">
              Open-Meteo · model estimate ·{' '}
              <a href="https://open-meteo.com/" target="_blank" rel="noreferrer">
                Weather data
              </a>
            </p>
          </>
        ) : (
          <div className="weather-empty">
            <Cloud />
            <h3>
              {location?.status === 'ready'
                ? 'Weather unavailable'
                : 'A little context for your day'}
            </h3>
            <p>
              {location?.status === 'ready'
                ? 'The weather service is not answering. Try refreshing shortly.'
                : 'Choose your location to see the weather, forecast and daylight hours here.'}
            </p>
            <button
              type="button"
              onClick={() =>
                location?.status === 'ready' ? void perform(loadResult) : setExpanded(true)
              }
              disabled={busy}
            >
              {location?.status === 'ready' ? 'Refresh weather' : 'Set location'}
            </button>
          </div>
        )}
      </article>

      <article className={`local-map-card${expanded ? ' is-expanded' : ''}`}>
        <button
          type="button"
          className="map-card-heading"
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
        >
          <span>
            <MapPin /> YOUR LOCATION
          </span>
          <span>
            <i
              className={location?.status === 'ready' ? 'location-dot' : 'location-dot is-muted'}
            />
            {stateLabel}
            <ChevronDown />
          </span>
        </button>
        {place || expanded ? (
          <LocationMap
            place={place}
            pins={pins}
            draft={draft}
            focus={focus}
            expanded={expanded}
            stale={location?.status !== 'ready'}
            onPick={pick}
          />
        ) : (
          <button type="button" className="map-empty" onClick={() => setExpanded(true)}>
            <Navigation />
            <span>{busy ? 'Finding your location…' : 'Make this your corner of the world'}</span>
            <small>Use Windows location or pin a place</small>
          </button>
        )}
        <div className="map-caption">
          <strong>{place?.label ?? 'No location selected'}</strong>
          <span>
            {place
              ? `${Math.abs(place.latitude).toFixed(4)}° ${place.latitude >= 0 ? 'N' : 'S'} · ${Math.abs(place.longitude).toFixed(4)}° ${place.longitude >= 0 ? 'E' : 'W'}`
              : 'You control location access'}
          </span>
          {place?.pinned && <small>{place.source}</small>}
          {place?.accuracy_m != null && (
            <small>
              {place.coarse ? 'Approximate · your internet provider' : place.source} · ±
              {Math.round(place.accuracy_m).toLocaleString()} m ·{' '}
              {place.timestamp
                ? new Date(place.timestamp * 1000).toLocaleTimeString([], {
                    hour: '2-digit',
                    minute: '2-digit'
                  })
                : ''}
            </small>
          )}
        </div>
        {expanded && (
          <div className="location-controls">
            {draft && (
              <form
                className="pin-editor"
                onSubmit={(event) => {
                  event.preventDefault()
                  void savePin()
                }}
              >
                <label htmlFor="pin-name">Name this pin</label>
                <div className="location-search">
                  <input
                    id="pin-name"
                    value={draft.name}
                    maxLength={160}
                    placeholder={draft.address.split(',')[0] || 'Home, Work, Gym…'}
                    onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                    autoFocus
                  />
                  <button disabled={busy}>Save pin</button>
                </div>
                <div className="location-mode-actions">
                  {['Home', 'Work', 'School', 'Gym'].map((name) => (
                    <button key={name} type="button" onClick={() => setDraft({ ...draft, name })}>
                      {name}
                    </button>
                  ))}
                  <button type="button" onClick={() => setDraft(null)}>
                    Cancel
                  </button>
                </div>
                <small>
                  {draft.address || 'Looking up the address…'} · {draft.latitude.toFixed(5)},{' '}
                  {draft.longitude.toFixed(5)} · drag the pin to adjust
                </small>
              </form>
            )}
            {place?.coarse && !place.pinned && !draft && (
              <p className="location-tip">
                This PC has no Wi-Fi or GPS, so Windows only knows your internet provider&apos;s
                location, which is in the right city but not your street. Click the map where you
                really are and save it as Home. Marvi will use that pin whenever Windows puts you
                nearby.
              </p>
            )}
            <form
              onSubmit={(event) => {
                event.preventDefault()
                void perform(async () => {
                  const result = await window.marvi?.searchPlaces(query)
                  if (!result)
                    throw new Error('Place search unavailable. Try again or click the map.')
                  setPlaces(result)
                  setSearched(true)
                  return true
                })
              }}
            >
              <label htmlFor="location-city">Find a place</label>
              <div className="location-search">
                <input
                  id="location-city"
                  value={query}
                  onChange={(event) => {
                    setQuery(event.target.value)
                    setSearched(false)
                    setPlaces([])
                  }}
                  maxLength={100}
                  placeholder="Address, street, shop or city"
                />
                <button disabled={busy || query.trim().length < 2}>Search</button>
              </div>
            </form>
            {searched && places.length === 0 && <p>No matches. Try a street or a nearby city.</p>}
            <div className="location-results">
              {places.map((candidate) => (
                <button
                  key={`${candidate.latitude},${candidate.longitude},${candidate.label}`}
                  disabled={busy}
                  type="button"
                  onClick={() => {
                    lookup.current++
                    setDraft({
                      latitude: candidate.latitude,
                      longitude: candidate.longitude,
                      name: '',
                      address: candidate.label
                    })
                    setPlaces([])
                    setSearched(false)
                  }}
                >
                  <MapPin />
                  <span>
                    {candidate.label}
                    {candidate.kind && <small>{candidate.kind}</small>}
                  </span>
                </button>
              ))}
            </div>
            {pins.length > 0 && (
              <ul className="location-pins" aria-label="Your pinned places">
                {pins.map((pin) => {
                  const main = same(pin, location?.settings.saved)
                  return (
                    <li key={`${pin.latitude},${pin.longitude},${pin.label}`}>
                      <button
                        type="button"
                        className="pin-name"
                        title="Show on map"
                        onClick={() =>
                          setFocus({
                            latitude: pin.latitude,
                            longitude: pin.longitude,
                            n: Date.now()
                          })
                        }
                      >
                        <MapPin /> {pin.label}
                        {main && <small>Main</small>}
                      </button>
                      {!main && (
                        <button
                          disabled={busy}
                          type="button"
                          onClick={() => void configure({ saved: pin })}
                        >
                          Make main
                        </button>
                      )}
                      <button
                        disabled={busy}
                        type="button"
                        aria-label={`Remove ${pin.label}`}
                        onClick={() => removePin(pin)}
                      >
                        Remove
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
            <div className="location-mode-actions">
              {location?.settings.mode !== 'automatic' && (
                <button
                  disabled={busy}
                  type="button"
                  onClick={() => void configure({ mode: 'automatic' })}
                >
                  <LocateFixed /> Use Windows location
                </button>
              )}
              {location?.settings.mode === 'automatic' && (
                <button
                  disabled={busy}
                  type="button"
                  onClick={() => void perform(() => window.marvi.refreshLocation())}
                >
                  <RefreshCw /> Refresh location
                </button>
              )}
              {location?.settings.saved && location.settings.mode !== 'saved' && (
                <button
                  disabled={busy}
                  type="button"
                  onClick={() => void configure({ mode: 'saved' })}
                >
                  Always use {location.settings.saved.label.split(',')[0]}
                </button>
              )}
              <button
                disabled={busy || location?.settings.mode === 'off'}
                type="button"
                onClick={() => void configure({ mode: 'off' })}
              >
                Turn off
              </button>
              {location?.settings.mode === 'automatic' && (
                <button type="button" onClick={() => void window.marvi?.openLocationSettings()}>
                  Windows permissions
                </button>
              )}
            </div>
            {location?.status === 'denied' && (
              <p>
                Windows location access is denied. Enable it in Windows permissions, or pin a place
                on the map.
              </p>
            )}
            {location?.settings.mode === 'automatic' &&
              ['unavailable', 'timeout', 'error', 'stale'].includes(location.status) && (
                <p>
                  Windows could not provide a fresh position. Refresh, or pin a place on the map.
                </p>
              )}
            <p className="location-disclosure">
              Weather requests share approximate coordinates with Open-Meteo. Place search and pin
              addresses are looked up with Photon (OpenStreetMap data). Map tiles share the viewed
              area with OpenStreetMap. Pins stay on this PC. Automatic fixes are not saved as
              location history; tool answers follow normal conversation retention.
            </p>
          </div>
        )}
        {place && (
          <a
            className="map-attribution"
            href="https://www.openstreetmap.org/copyright"
            target="_blank"
            rel="noreferrer"
          >
            © OpenStreetMap contributors
          </a>
        )}
        {busy && (
          <p className="location-feedback" role="status">
            Updating… Windows may ask for location permission.
          </p>
        )}
        {error && (
          <p className="location-feedback" role="alert">
            {error}
          </p>
        )}
      </article>
    </section>
  )

  async function loadResult(): Promise<boolean> {
    await load()
    return true
  }
}
