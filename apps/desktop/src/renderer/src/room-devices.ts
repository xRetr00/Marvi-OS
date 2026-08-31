/**
 * What to say about a room device that is not working.
 *
 * There are four different reasons and they need four different answers,
 * because each one sends the reader somewhere else: to a terminal, to the
 * settings, to the wall socket, or nowhere at all.
 *
 * The order is the point. The bulb showed "given up after 11,359 failed
 * attempts" while the real story was that `tinytuya` had never been installed —
 * the sidecar's own log said "Tuya control disabled" on every start. Eleven
 * thousand attempts is a true number and a useless one when nothing was ever
 * able to talk to the device; it reads as a broken bulb and sends somebody to
 * check a plug that was fine.
 *
 * So a missing driver is said first and stops there. It explains everything
 * beneath it.
 */

export interface DeviceHealth {
  /** From `room_health`. Whether an address and key are configured. */
  configured?: unknown
  online?: unknown
  ip?: unknown
}

export interface DeviceCounters {
  /** From `room_state`. The sidecar's own failure bookkeeping. */
  consecutive_failures?: unknown
  circuit_open?: unknown
}

/**
 * @param driver Name of the Python library the sidecar is missing for this
 *   device, or "" when it has one.
 */
export function deviceStory(
  driver: string,
  device: DeviceHealth,
  counters: DeviceCounters
): string {
  if (driver) {
    return `${driver} is not installed, so this cannot be reached at all. Nothing below is about the device.`
  }
  if (!device.configured) {
    return 'No address or key configured for it yet.'
  }
  if (counters.circuit_open) {
    const failures = Number(counters.consecutive_failures ?? 0).toLocaleString()
    // Switched off at the wall is a normal thing to do to a lamp, not a fault
    // to be alarmed by, and the sidecar picks it up again on its own.
    return `Not reachable — stopped trying after ${failures} attempts. Switched off at the wall counts, and it will pick up again by itself.`
  }
  if (device.ip) {
    return String(device.ip)
  }
  return 'Configured, and nothing has answered yet.'
}

/** The pill beside it: three states, and "no driver" is not an error. */
export function deviceTone(driver: string, device: DeviceHealth): 'neutral' | 'ready' | 'danger' {
  if (driver || !device.configured) return 'neutral'
  return device.online ? 'ready' : 'danger'
}

export function deviceStanding(driver: string, device: DeviceHealth): string {
  if (driver) return 'no driver'
  if (!device.configured) return 'not set up'
  return device.online ? 'online' : 'offline'
}
