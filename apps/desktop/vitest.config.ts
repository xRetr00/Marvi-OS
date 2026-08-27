import { configDefaults, defineConfig } from 'vitest/config'

/**
 * What counts as this project's tests.
 *
 * Resource and distribution trees can carry copied test files written for
 * another harness. If Vitest collects those files, `npm test` stops being a
 * signal about the desktop app and may also run the same tests twice.
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
