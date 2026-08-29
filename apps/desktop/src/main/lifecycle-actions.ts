export interface ApplicationLifecycle {
  quit: () => void
  relaunch: () => void
}

/** Relaunch first, then enter the normal quit path that synchronously stops every owned process. */
export function restartApplication(application: ApplicationLifecycle): void {
  application.relaunch()
  application.quit()
}

/** The normal quit path owns service, tray, Island, and child-process teardown. */
export function shutdownApplication(application: ApplicationLifecycle): void {
  application.quit()
}
