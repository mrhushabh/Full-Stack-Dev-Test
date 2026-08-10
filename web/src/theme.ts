import { useCallback, useEffect, useState } from 'react'

/**
 * Light, dark, or follow the device.
 *
 * The choice is deliberate rather than cosmetic: light for daylight and roofs,
 * dark for basements, crawlspaces and evening calls. A tech should be able to
 * change it on the stairs without leaving the app, so the override is stored
 * per-device and beats the OS setting in both directions.
 */

export type Theme = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'field-estimate-theme'

export function readStoredTheme(): Theme {
  const stored = localStorage.getItem(STORAGE_KEY)
  return stored === 'light' || stored === 'dark' ? stored : 'system'
}

export function applyTheme(theme: Theme) {
  const root = document.documentElement
  if (theme === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', theme)
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(readStoredTheme)

  useEffect(() => {
    applyTheme(theme)
    if (theme === 'system') localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, theme)
  }, [theme])

  /** Cycles light -> dark -> follow device. */
  const cycle = useCallback(() => {
    setTheme((current) =>
      current === 'light' ? 'dark' : current === 'dark' ? 'system' : 'light',
    )
  }, [])

  return { theme, setTheme, cycle }
}
