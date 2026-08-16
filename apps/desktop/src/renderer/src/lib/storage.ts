function storageAvailable(): boolean {
  try {
    return typeof window !== 'undefined' && Boolean(window.localStorage)
  } catch {
    return false
  }
}

export function storedString(key: string): string | null {
  if (!storageAvailable()) return null
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

export function persistString(key: string, value: string): void {
  if (!storageAvailable()) return
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // Storage full or blocked — the in-memory store keeps working.
  }
}
