export interface Place {
  latitude: number
  longitude: number
  label: string
  timezone: string
}
export interface LocationSettings {
  mode: 'off' | 'automatic' | 'saved'
  saved: Place | null
}
export interface LocationState {
  settings: LocationSettings
  generation: number
  status: 'off' | 'ready' | 'stale' | 'denied' | 'unavailable' | 'timeout' | 'error'
  place: (Place & { accuracy_m: number | null; timestamp: number | null; source: string }) | null
}
export interface WeatherState {
  status: 'ready' | 'stale' | 'unavailable'
  detail?: string
  data: {
    current: { time: string; temperature_2m: number; apparent_temperature: number; relative_humidity_2m: number; weather_code: number; wind_speed_10m: number; is_day: number }
    daily: { time: string[]; weather_code: number[]; temperature_2m_max: number[]; temperature_2m_min: number[]; precipitation_probability_max: number[]; sunrise: string[]; sunset: string[] }
    units: Record<string, string>
    timezone: string
    fetched_at: number
    source: string
    kind: string
  } | null
}
