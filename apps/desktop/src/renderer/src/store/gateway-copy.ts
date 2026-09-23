import { interpolate, t } from './locale'

/** Translate Gateway-owned status prose at the display boundary. Raw diagnostics stay intact. */
export function gatewayCopy(detail: string | null | undefined): string {
  const value = (detail ?? '').trim()
  if (!value) return ''
  const connected = /^(\d+) connected(?:, (\d+) need reconnect)?$/.exec(value)
  if (connected)
    return connected[2]
      ? interpolate('{connected} connected, {stale} need reconnect', { connected: Number(connected[1]), stale: Number(connected[2]) })
      : interpolate('{connected} connected', { connected: Number(connected[1]) })
  const camera = /^Smart Room camera online, (\d+) visible, (.*)$/.exec(value)
  if (camera)
    return interpolate('Smart Room camera online, {count} visible, {owner}', {
      count: Number(camera[1]), owner: camera[2]
    })
  return t(value)
}
