/** How an image size is written for a person: `1024x1024` -> `1024 × 1024`.
 *
 * Its own file rather than beside the component: a module that exports both
 * a component and a helper loses fast refresh.
 */

export function prettySize(size: unknown): string {
  const raw = typeof size === 'string' ? size.trim() : ''
  const match = /^(\d+)\s*[x×]\s*(\d+)$/i.exec(raw)
  return match ? `${match[1]} × ${match[2]}` : raw || '1024 × 1024'
}
