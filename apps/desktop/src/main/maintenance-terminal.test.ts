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
    expect(maintenancePowerShellArgs({ action: 'doctor' }, 'C:\\uv.exe', 'D:\\Marvi')).toBeNull()
  })

  it('runs the fixed command through the managed environment and keeps the terminal open', () => {
    expect(maintenancePowerShellArgs('doctor', "C:\\Marvi's Tools\\uv.exe", 'D:\\Marvi OS')).toEqual([
      '-NoLogo',
      '-NoProfile',
      '-ExecutionPolicy',
      'Bypass',
      '-NoExit',
      '-Command',
      "& 'C:\\Marvi''s Tools\\uv.exe' run --project 'D:\\Marvi OS' marvi doctor"
    ])
  })
})
