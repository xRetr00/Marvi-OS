import { configDefaults, defineConfig } from 'vitest/config'

/**
 * What counts as this project's tests.
 *
 * There was no config at all, which was fine until `resources/messaging-runtime`
 * arrived: a vendored tree carrying 1,510 test files of its own. Vitest
 * collected all of them, 963 failed — they are written for their own harness,
 * not this one — and `npm test` stopped being a signal about the desktop app.
 * Thirty-nine real files passing was invisible inside it.
 *
 * Vendored code is tested by whoever vendored it, at the version it was
 * vendored at. Running someone else's suite here reports on their repository
 * rather than on this one, and a red suite that is always red gets ignored,
 * which costs more than it ever catches.
 */
export default defineConfig({
  test: {
    // `dist/` for the same reason and a worse one: a packaged build contains a
    // copy of everything, so without this the suite tests the last release
    // alongside the working tree and doubles every count.
    exclude: [...configDefaults.exclude, 'resources/**', 'dist/**', 'out/**']
  }
})
