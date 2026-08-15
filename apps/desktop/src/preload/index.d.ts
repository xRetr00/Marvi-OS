export interface MarviDesktopApi {
  getVersion: () => Promise<string>
  showMain: () => void
}

declare global {
  interface Window {
    marvi: MarviDesktopApi
  }
}
