/** WMO interpretation codes returned by Open-Meteo. */
export function weatherLabel(code: number): string {
  if (code === 0) return 'Clear skies'
  if (code >= 1 && code <= 3)
    return ['Clear skies', 'Mostly clear', 'Partly cloudy', 'Overcast'][code] ?? 'Unknown'
  if ([45, 48].includes(code)) return 'Fog'
  if (code >= 51 && code <= 57) return 'Drizzle'
  if (code >= 61 && code <= 67) return 'Rain'
  if (code >= 71 && code <= 77) return 'Snow'
  if (code >= 80 && code <= 82) return 'Rain showers'
  if (code === 85 || code === 86) return 'Snow showers'
  if (code >= 95 && code <= 99) return 'Thunderstorms'
  return 'Conditions unavailable'
}
