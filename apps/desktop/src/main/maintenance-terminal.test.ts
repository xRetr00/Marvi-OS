import { describe, expect, it } from 'vitest'

import { maintenanceCommand, maintenancePowerShellArgs } from './maintenance-terminal'

describe('maintenance terminal actions', () => {
  it('maps the four renderer actions to fixed commands', () => {
    expect(maintenanceCommand('doctor')).toBe('marvi doctor')
    expect(maintenanceCommand('setup')).toBe('marvi setup')
    expect(maintenanceCommand('models')).toBe('marvi models list')
    expect(maintenanceCommand('diagnostics')).toBe('marvi diagnostics')
  })

  it('rejects arbitrary renderer input instead of treating it as a command', () => {
    expect(maintenanceCommand('doctor; Remove-Item C:\\')).toBeNull()
    expect(maintenancePowerShellArgs({ action: 'doctor' })).toBeNull()
  })

  it('keeps the terminal open after the command finishes', () => {
    expect(maintenancePowerShellArgs('doctor')).toEqual([
      '-NoExit',
      '-Command',
      'marvi doctor'
    ])
  })
})
