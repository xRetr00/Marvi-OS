/** Where a new tab or an empty address goes. Not `about:blank`: a white page
 *  with nothing on it read as a browser that had failed to load. */
export const START_PAGE = 'https://www.google.com'

/** Convert ordinary address-bar input into an HTTP(S) URL. */
export function toAddress(text: string): string {
  const raw = text.trim()
  if (!raw) return START_PAGE
  if (/^[a-z][a-z0-9+.-]*:/i.test(raw)) return raw
  if (!/\s/.test(raw) && /^[^\s/]+\.[a-z]{2,}(:\d+)?(\/.*)?$/i.test(raw)) {
    return `https://${raw}`
  }
  return `https://www.google.com/search?q=${encodeURIComponent(raw)}`
}
