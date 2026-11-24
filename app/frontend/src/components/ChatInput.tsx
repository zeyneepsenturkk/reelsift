import { useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react'

type Props = {
  placeholder: string
  // `false` dönerse metin kutuda kalır (gönderilemedi); aksi halde kutu temizlenir.
  onSend: (text: string) => boolean | void | Promise<boolean | void>
  streaming?: boolean
  onStop?: () => void
  autoFocus?: boolean
}

const MAX_LINES = 6

export function ChatInput({ placeholder, onSend, streaming = false, onStop, autoFocus = false }: Props) {
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const field = useRef<HTMLTextAreaElement>(null)

  // Kutu 6 satıra kadar kendiliğinden büyür, sonra kaydırılır.
  useLayoutEffect(() => {
    const el = field.current
    if (!el) return
    el.style.height = 'auto'
    const lineHeight = parseFloat(getComputedStyle(el).lineHeight) || 24
    const max = lineHeight * MAX_LINES
    el.style.height = `${Math.min(el.scrollHeight, max)}px`
    el.style.overflowY = el.scrollHeight > max ? 'auto' : 'hidden'
  }, [value])

  const submit = async () => {
    const text = value.trim()
    if (!text || busy) return
    setBusy(true)
    try {
      const result = await onSend(text)
      if (result !== false) setValue('')
    } finally {
      setBusy(false)
      field.current?.focus()
    }
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return
    event.preventDefault()
    if (!streaming) void submit()
  }

  return (
    <div className="box">
      <textarea
        ref={field}
        value={value}
        rows={1}
        placeholder={placeholder}
        aria-label={placeholder}
        autoFocus={autoFocus}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={onKeyDown}
      />
      {streaming ? (
        <button className="send stop" type="button" aria-label="Durdur" onClick={onStop} />
      ) : (
        <button className="send" type="button" aria-label="Gönder" onClick={() => void submit()}>
          ↑
        </button>
      )}
    </div>
  )
}
