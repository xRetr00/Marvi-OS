import { defineConfig } from 'eslint/config'
import tseslint from '@electron-toolkit/eslint-config-ts'
import eslintConfigPrettier from '@electron-toolkit/eslint-config-prettier'
import eslintPluginReact from 'eslint-plugin-react'
import eslintPluginReactHooks from 'eslint-plugin-react-hooks'
import eslintPluginReactRefresh from 'eslint-plugin-react-refresh'

export default defineConfig(
  {
    // Vendored and shipped-as-is code is linted by whoever wrote it, at the
    // version it was vendored at.
    //
    // `resources/` is the browser-extension bundle: it runs in Chrome, against
    // Chrome's globals, and is not part of this app's TypeScript at all.
    //
    // Vendored code is linted by whoever vendored it, at the version it was
    // vendored at -- the same reason `vitest.config.ts` excludes it from the
    // suite. Reformatting someone else's tree to this project's rules makes
    // the next update a merge conflict and reports on their repository rather
    // than on this one.
    ignores: [
      '**/node_modules',
      '**/dist',
      '**/out',
      '**/orb/engine/**',
      'src/main/vendor/**',
      'resources/**'
    ]
  },
  tseslint.configs.recommended,
  eslintPluginReact.configs.flat.recommended,
  eslintPluginReact.configs.flat['jsx-runtime'],
  {
    settings: {
      react: {
        version: 'detect'
      }
    }
  },
  {
    files: ['**/*.{ts,tsx}'],
    plugins: {
      'react-hooks': eslintPluginReactHooks,
      'react-refresh': eslintPluginReactRefresh
    },
    rules: {
      ...eslintPluginReactHooks.configs.recommended.rules,
      ...eslintPluginReactRefresh.configs.vite.rules
    }
  },
  eslintConfigPrettier
)
