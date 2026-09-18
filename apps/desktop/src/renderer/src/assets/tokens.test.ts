import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

// ponytail: regex over the source text, not a real parser — enough to catch a token that is
// used without a fallback but never defined, which silently voids the whole declaration.
const srcRoot = join(__dirname, '..')

function sourceFiles(ext: string[]): string[] {
  return readdirSync(srcRoot, { recursive: true, encoding: 'utf8' })
    .filter((name) => ext.some((e) => name.endsWith(e)))
    .map((name) => join(srcRoot, name))
}

describe('css custom properties', () => {
  it('defines every token that is used without a fallback', () => {
    const defined = new Set<string>()
    const used = new Map<string, string>()

    // .tsx counts as a definition site: components set tokens via inline style objects.
    for (const file of sourceFiles(['.css', '.ts', '.tsx'])) {
      const source = readFileSync(file, 'utf8')
      for (const [, name] of source.matchAll(/(--[\w-]+)'?"?\s*:/g)) defined.add(name)
      // A var() with no comma has no fallback. --radix-* tokens are injected by Radix at runtime.
      for (const [, name] of source.matchAll(/var\(\s*(--[\w-]+)\s*\)/g)) {
        if (!name.startsWith('--radix-') && !used.has(name)) used.set(name, file)
      }
    }

    const missing = [...used].filter(([name]) => !defined.has(name))
    expect(missing).toEqual([])
  })
})
