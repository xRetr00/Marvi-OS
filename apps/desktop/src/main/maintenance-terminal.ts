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

function quotePowerShell(value: string): string {
  return `'${value.replaceAll("'", "''")}'`
}

export function maintenancePowerShellArgs(
  value: unknown,
  uvPath: string,
  gatewayProject: string
): string[] | null {
  const command = maintenanceCommand(value)
  if (!command || !uvPath || !gatewayProject) return null
  const invocation = `& ${quotePowerShell(uvPath)} run --project ${quotePowerShell(gatewayProject)} ${command}`
  return ['-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-NoExit', '-Command', invocation]
}
