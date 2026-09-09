export interface ComputerStatus {
  enabled: boolean
  installed: boolean
  state: 'idle' | 'running' | 'stopping' | 'paused' | 'private' | 'unknown' | 'unavailable'
  active: boolean
  action: string
  driver: string
  version: string
  revision?: number
}
export type ComputerCommand = 'stop' | 'private' | 'resume'
