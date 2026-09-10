/**
 * The browser handoff poll, split from the island it feeds so that file
 * exports only components and keeps fast refresh.
 */

import { useEffect, useState } from 'react'

import type { BrowserSession } from '../../../shared/browser'

export function useBrowserHandoff(): BrowserSession | null {
  const [session, setSession] = useState<BrowserSession | null>(null)
  useEffect(() => {
    let alive = true
    const refresh = async (): Promise<void> => {
      try {
        const status = await window.marvi?.getBrowser()
        if (alive)
          setSession(
            status?.sessions.find((s) => s.state === 'private') ??
              status?.sessions.find((s) =>
                ['running', 'starting', 'stopping', 'resuming'].includes(s.state)
              ) ??
              null
          )
      } catch {
        if (alive) setSession(null)
      }
    }
    void refresh()
    const timer = setInterval(() => {
      void refresh()
    }, 1500)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [])
  return session
}
