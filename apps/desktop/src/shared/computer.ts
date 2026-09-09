export interface ComputerStatus {
  enabled: boolean
  installed: boolean
  state: 'idle' | 'running' | 'stopping' | 'paused' | 'private' | 'unavailable'
  active: boolean
  action: string
  driver: string
  version: string
}
export type ComputerCommand = 'stop' | 'private' | 'resume'
