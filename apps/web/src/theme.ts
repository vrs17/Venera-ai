// Theme state: 'light' | 'dark', persisted to localStorage and reflected as a
// data-theme attribute on <html> (index.html sets it pre-paint to avoid a flash;
// this module keeps it in sync after hydration).

export type Theme = 'light' | 'dark'

const KEY = 'venera_theme'

export function getInitialTheme(): Theme {
  const saved = localStorage.getItem(KEY)
  if (saved === 'light' || saved === 'dark') return saved
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function applyTheme(theme: Theme): void {
  document.documentElement.setAttribute('data-theme', theme)
  localStorage.setItem(KEY, theme)
}
