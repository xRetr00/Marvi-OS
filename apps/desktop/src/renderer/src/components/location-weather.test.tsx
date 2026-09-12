import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { LocationClock, LocationWeather } from './location-weather'
import { weatherLabel } from '../../../shared/weather'

describe('location presentation', () => {
  it('offers setup without fabricated weather or a fake live map', () => {
    const html = renderToStaticMarkup(<LocationWeather />)
    expect(html).toContain('Set location')
    expect(html).toContain('No location selected')
    expect(html).not.toContain('San Francisco')
    expect(html).not.toContain('leaflet-tile')
  })
  it('renders a real clock and recognizes WMO condition groups', () => {
    expect(renderToStaticMarkup(<LocationClock />)).toMatch(/<time.*datetime=/i)
    expect(weatherLabel(0)).toBe('Clear skies')
    expect(weatherLabel(65)).toBe('Rain')
    expect(weatherLabel(75)).toBe('Snow')
    expect(weatherLabel(95)).toBe('Thunderstorms')
    expect(weatherLabel(-1)).toBe('Conditions unavailable')
  })
})
