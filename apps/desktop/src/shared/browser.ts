export type BrowserCommand = 'pause' | 'private' | 'resume' | 'stop' | 'show' | 'close'
export interface BrowserSession {
  id: string
  profile_id: string
  objective: string
  revision: number
  state: string
  detail: string
  tabs: { id: string; url: string; target?: string }[]
  host?: 'embedded' | 'native'
  download?: { artifact: string; bytes: number; sha256: string }
}
export interface BrowserPlacement {
  id: string
  target?: string
  bounds: { x: number; y: number; width: number; height: number }
}
export interface BrowserStatus {
  available: boolean
  driver: string
  private_input: boolean
  profiles: { id: string; label: string }[]
  sessions: BrowserSession[]
}
export interface BrowserStart {
  profile_id: string
  url: string
  objective: string
}
export interface BrowserProfileEdit {
  action: 'create' | 'rename' | 'delete'
  profile_id?: string
  label?: string
}
