import assert from 'node:assert/strict'
import test from 'node:test'

import {
  updateMarviLockPackages,
  updateNamedTomlSection,
  updatePackageLock,
  updateUpdaterWorkspace,
} from './sync-version.mjs'

test('package lock changes only Marvi workspace packages', () => {
  const source = JSON.stringify({
    version: '0.9.0',
    packages: {
      '': { name: 'marvi-os', version: '0.9.0' },
      'apps/desktop': { name: 'marvi-os-desktop', version: '0.9.0' },
      'node_modules/example': { name: 'example', version: '0.9.0' },
    },
  }, null, 2) + '\n'
  const value = JSON.parse(updatePackageLock(source, '0.10.0'))
  assert.equal(value.version, '0.10.0')
  assert.equal(value.packages[''].version, '0.10.0')
  assert.equal(value.packages['apps/desktop'].version, '0.10.0')
  assert.equal(value.packages['node_modules/example'].version, '0.9.0')
})

test('Python and native app manifests update their Marvi package section', () => {
  const python = '[build-system]\nrequires = []\n\n[project]\nname = "marvi-os-gateway"\nversion = "0.1.0.dev0"\n'
  const rust = '[package]\nname = "marvi-wake-host"\nversion = "0.1.0"\n\n[dependencies]\nserde = "1"\n'
  assert.match(updateNamedTomlSection(python, 'project', '0.10.0'), /version = "0\.10\.0"/)
  assert.match(updateNamedTomlSection(rust, 'package', '0.10.0'), /version = "0\.10\.0"/)
})

test('lock updates are scoped to Marvi package blocks', () => {
  const lock = 'version = 1\n\n[[package]]\nname = "example"\nversion = "0.9.0"\n\n[[package]]\nname = "marvi-os-agent"\nversion = "0.1.0.dev0"\nsource = { editable = "." }\n'
  const updated = updateMarviLockPackages(lock, '0.10.0')
  assert.match(updated, /name = "example"\nversion = "0\.9\.0"/)
  assert.match(updated, /name = "marvi-os-agent"\nversion = "0\.10\.0"/)
})

test('updater workspace version is independent from dependency versions', () => {
  const cargo = '[workspace]\nmembers = []\n\n[workspace.package]\nversion = "0.9.0"\n\n[profile.release]\nopt-level = "s"\n'
  const updated = updateUpdaterWorkspace(cargo, '0.10.0')
  assert.match(updated, /\[workspace\.package\]\nversion = "0\.10\.0"/)
})
