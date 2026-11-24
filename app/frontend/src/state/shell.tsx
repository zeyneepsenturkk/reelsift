import { createContext, useCallback, useContext, useMemo, useState, useSyncExternalStore, type ReactNode } from 'react'
import { readStored, writeStored } from '../lib/storage.ts'

export type PanelMode = 'closed' | 'open' | 'full'

type ShellValue = {
  // Kullanıcının tercihi; tam ekranda kenar çubuğu ayrıca daralmış çizilir.
  slim: boolean
  toggleSlim: () => void
  panel: PanelMode
  setPanel: (mode: PanelMode) => void
  // Pencere 1160 px altındaysa 256 + 380 + 520 sığmaz: panel açıkken kenar çubuğu geçici olarak 64 px'e daralır
  // (kayıtlı tercih değişmez; panel kapanınca ya da pencere genişleyince tercihe dönülür).
  compact: boolean
}

const SLIM_KEY = 'reelsift.slim'
const ShellContext = createContext<ShellValue | null>(null)

// 900 px altında kenar çubuğu daraltılmış başlar; kayıtlı tercih varsa o geçerli.
function initialSlim(): boolean {
  const stored = readStored(SLIM_KEY)
  if (stored !== null) return stored === '1'
  return window.matchMedia('(max-width: 899px)').matches
}

const COMPACT_QUERY = '(max-width: 1159px)'

// Modül düzeyinde sabit: satır içi tanımlanırsa her render'da yeni kimlik alır ve React aboneliği boşuna yeniden kurar.
function subscribeCompact(notify: () => void): () => void {
  const query = window.matchMedia(COMPACT_QUERY)
  query.addEventListener('change', notify)
  return () => query.removeEventListener('change', notify)
}

const getCompact = () => window.matchMedia(COMPACT_QUERY).matches
const getCompactOnServer = () => false

function useCompact(): boolean {
  return useSyncExternalStore(subscribeCompact, getCompact, getCompactOnServer)
}

export function ShellProvider({ children }: { children: ReactNode }) {
  const [slim, setSlim] = useState(initialSlim)
  const [panel, setPanel] = useState<PanelMode>('closed')
  const compact = useCompact()

  const toggleSlim = useCallback(() => {
    setSlim((current) => {
      writeStored(SLIM_KEY, current ? '0' : '1')
      return !current
    })
  }, [])

  const value = useMemo(() => ({ slim, toggleSlim, panel, setPanel, compact }), [slim, toggleSlim, panel, compact])
  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>
}

export function useShell(): ShellValue {
  const value = useContext(ShellContext)
  if (!value) throw new Error('ShellProvider eksik')
  return value
}
