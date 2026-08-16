export interface MarviDesktopApi {
  getVersion: () => Promise<string>
  showMain: () => void
  pushIslandState: (state: unknown) => void
  onIslandState: (listener: (state: unknown) => void) => () => void
  setIslandSize: (size: { width: number; height: number }) => void
  setIslandInteractive: (interactive: boolean) => void
}

declare global {
  interface Window {
    marvi: MarviDesktopApi
  }
}
