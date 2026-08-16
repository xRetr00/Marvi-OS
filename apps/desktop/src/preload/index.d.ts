export interface MarviDesktopApi {
  getVersion: () => Promise<string>
  getBuildInfo: () => Promise<MarviBuildInfo>
  showMain: () => void
  pushIslandState: (state: unknown) => void
  onIslandState: (listener: (state: unknown) => void) => () => void
  setIslandSize: (size: { width: number; height: number }) => void
  setIslandInteractive: (interactive: boolean) => void
}

export interface MarviBuildInfo {
  version: string
  commit: string
  buildTime: string
  platform: string
  arch: string
  updateChannel: string
}

declare global {
  interface Window {
    marvi: MarviDesktopApi
  }
}
