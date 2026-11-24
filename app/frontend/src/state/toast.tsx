import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, type ReactNode } from 'react'
import { initialToast, toastReducer } from '../lib/toast.ts'

type ToastValue = {
  // `owner` verilirse bildirim yalnız o sahibin `clear`'ı ile erken kapanır.
  say: (message: string, owner?: string) => void
  clear: (owner: string) => void
}

const ToastContext = createContext<ToastValue | null>(null)

// Taslaktaki toast: tek öğe, metin değişir, 2,2 sn sonra kaybolur (görünürlük CSS geçişiyle).
export function ToastProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(toastReducer, initialToast)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const say = useCallback((message: string, owner?: string) => {
    dispatch({ type: 'show', message, owner: owner ?? null })
    clearTimeout(timer.current)
    timer.current = setTimeout(() => dispatch({ type: 'hide' }), 2200)
  }, [])

  const clear = useCallback((owner: string) => dispatch({ type: 'clear', owner }), [])

  useEffect(() => () => clearTimeout(timer.current), [])

  const value = useMemo(() => ({ say, clear }), [say, clear])
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className={`toast${state.visible ? ' on' : ''}`} role="status" aria-live="polite">
        {state.message}
      </div>
    </ToastContext.Provider>
  )
}

function useToastValue(): ToastValue {
  const value = useContext(ToastContext)
  if (!value) throw new Error('ToastProvider eksik')
  return value
}

export const useToast = (): ToastValue['say'] => useToastValue().say
export const useClearToast = (): ToastValue['clear'] => useToastValue().clear
