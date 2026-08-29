import type { MaintenanceAction } from '../shared/runtime'

const COMMANDS: Readonly<Record<MaintenanceAction, string>> = Object.freeze({
  doctor: 'marvi doctor',
  setup: 'marvi setup',
  models: 'marvi models list',
  diagnostics: 'marvi diagnostics'
})

export function maintenanceCommand(value: unknown): string | null {
  return typeof value === 'string' && Object.hasOwn(COMMANDS, value)
    ? COMMANDS[value as MaintenanceAction]
    : null
}

export function maintenancePowerShellArgs(value: unknown): string[] | null {
  const command = maintenanceCommand(value)
  return command ? ['-NoExit', '-Command', command] : null
}
