#!/usr/bin/env node

import { access, readdir, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const SEMVER = /^\d+\.\d+\.\d+$/

function preserveJsonLayout(source, value) {
  const eol = source.includes('\r\n') ? '\r\n' : '\n'
  const trailing = source.endsWith('\n') ? eol : ''
  return JSON.stringify(value, null, 2).replaceAll('\n', eol) + trailing
}

export function updatePackageJson(source, version) {
  const value = JSON.parse(source)
  value.version = version
  return preserveJsonLayout(source, value)
}

export function updatePackageLock(source, version) {
  const value = JSON.parse(source)
  value.version = version
  for (const entry of Object.values(value.packages ?? {})) {
    if (entry && typeof entry.name === 'string' && /^marvi-os(?:-|$)/.test(entry.name)) {
      entry.version = version
    }
  }
  return preserveJsonLayout(source, value)
}

export function updateTauriConfig(source, version) {
  const value = JSON.parse(source)
  value.version = version
  return preserveJsonLayout(source, value)
}

export function updateNamedTomlSection(source, section, version) {
  const header = `[${section}]`
  const start = source.indexOf(header)
  if (start < 0) throw new Error(`missing ${header}`)
  const next = source.indexOf('\n[', start + header.length)
  const end = next < 0 ? source.length : next
  const block = source.slice(start, end)
  const name = block.match(/^name\s*=\s*"(marvi-[^"]+)"/m)?.[1]
  if (!name) throw new Error(`${header} does not describe a Marvi package`)
  if (!/^version\s*=\s*"[^"]+"/m.test(block)) {
    throw new Error(`${name} has no version in ${header}`)
  }
  const updated = block.replace(/^version\s*=\s*"[^"]+"/m, `version = "${version}"`)
  return source.slice(0, start) + updated + source.slice(end)
}

export function updateUpdaterWorkspace(source, version) {
  const header = '[workspace.package]'
  const start = source.indexOf(header)
  if (start < 0) throw new Error(`missing ${header}`)
  const next = source.indexOf('\n[', start + header.length)
  const end = next < 0 ? source.length : next
  const block = source.slice(start, end)
  if (!/^version\s*=\s*"[^"]+"/m.test(block)) {
    throw new Error(`${header} has no version`)
  }
  const updated = block.replace(/^version\s*=\s*"[^"]+"/m, `version = "${version}"`)
  return source.slice(0, start) + updated + source.slice(end)
}

export function updateMarviLockPackages(source, version) {
  const parts = source.split(/(?=^\[\[package\]\]\r?$)/m)
  let found = 0
  const updated = parts.map((block) => {
    if (!/^\[\[package\]\]/m.test(block) || !/^name\s*=\s*"marvi-[^"]+"/m.test(block)) {
      return block
    }
    if (!/^version\s*=\s*"[^"]+"/m.test(block)) {
      throw new Error(`Marvi package lock entry has no version: ${block.slice(0, 100)}`)
    }
    found += 1
    return block.replace(/^version\s*=\s*"[^"]+"/m, `version = "${version}"`)
  })
  if (found === 0) throw new Error('lockfile contains no Marvi package entries')
  return updated.join('')
}

async function existingChildren(root, directory, file) {
  const parent = path.join(root, directory)
  const entries = await readdir(parent, { withFileTypes: true })
  const candidates = entries
    .filter((entry) => entry.isDirectory())
    .map((entry) => path.join(directory, entry.name, file))
  const existing = await Promise.all(candidates.map(async (relative) => {
    try {
      await access(path.join(root, relative))
      return relative
    } catch {
      return null
    }
  }))
  return existing.filter(Boolean)
}

export async function synchronize(root, version, check = false) {
  if (!SEMVER.test(version)) throw new Error(`version must be stable SemVer, got ${version}`)

  const jobs = [
    ['VERSION', () => `${version}\n`],
    ['package.json', (source) => updatePackageJson(source, version)],
    ['package-lock.json', (source) => updatePackageLock(source, version)],
    ['apps/updater/Cargo.toml', (source) => updateUpdaterWorkspace(source, version)],
    ['apps/updater/Cargo.lock', (source) => updateMarviLockPackages(source, version)],
    ['apps/updater/src-tauri/tauri.conf.json', (source) => updateTauriConfig(source, version)],
  ]

  for (const relative of await existingChildren(root, 'services', 'pyproject.toml')) {
    jobs.push([relative, (source) => updateNamedTomlSection(source, 'project', version)])
  }
  for (const relative of await existingChildren(root, 'services', 'uv.lock')) {
    jobs.push([relative, (source) => updateMarviLockPackages(source, version)])
  }
  jobs.push(['uv.lock', (source) => updateMarviLockPackages(source, version)])

  for (const relative of await existingChildren(root, 'apps', 'Cargo.toml')) {
    if (relative.replaceAll('\\', '/') === 'apps/updater/Cargo.toml') continue
    jobs.push([relative, (source) => updateNamedTomlSection(source, 'package', version)])
  }
  for (const relative of await existingChildren(root, 'apps', 'Cargo.lock')) {
    if (relative.replaceAll('\\', '/') === 'apps/updater/Cargo.lock') continue
    jobs.push([relative, (source) => updateMarviLockPackages(source, version)])
  }

  const changed = []
  for (const [relative, transform] of jobs) {
    const absolute = path.join(root, relative)
    let source
    try {
      source = await readFile(absolute, 'utf8')
    } catch (error) {
      if (error.code === 'ENOENT' && /(?:services|apps)[/\\][^/\\]+[/\\](?:uv\.lock|Cargo\.lock)$/.test(relative)) {
        continue
      }
      throw error
    }
    const updated = transform(source)
    if (updated !== source) {
      changed.push(relative.replaceAll('\\', '/'))
      if (!check) await writeFile(absolute, updated, 'utf8')
    }
  }
  return changed.sort()
}

async function main() {
  const args = process.argv.slice(2)
  const check = args[0] === '--check'
  const version = args[check ? 1 : 0]
  if (!version || args.length !== (check ? 2 : 1)) {
    throw new Error('usage: node scripts/sync-version.mjs [--check] <version>')
  }
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
  const changed = await synchronize(root, version, check)
  if (check && changed.length) {
    console.error(`Version ${version} is not synchronized in:\n${changed.map((file) => `  ${file}`).join('\n')}`)
    process.exitCode = 1
    return
  }
  console.log(check ? `All product manifests match ${version}.` : `Synchronized ${version} in ${changed.length} files.`)
  for (const file of changed) console.log(`  ${file}`)
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(error.message)
    process.exitCode = 1
  })
}
