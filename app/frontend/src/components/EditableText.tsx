import { useLayoutEffect, useRef, type KeyboardEvent } from 'react'

type Props = {
  value: string
  editable: boolean
  onCommit: (value: string) => void
  as: 'h2' | 'p'
  className: string
  label: string
  placeholder?: string
  allowEmpty?: boolean
}

// Yerinde düzenlenen metin: odaktan çıkınca ya da Enter'da kaydedilir, Esc eski metne döner.
// İçerik React yerine DOM'da tutulur ki yazarken imleç sıçramasın; dışarıdan değer değişince odakta değilse yazılır.
export function EditableText({ value, editable, onCommit, as: Tag, className, label, placeholder, allowEmpty = false }: Props) {
  const ref = useRef<HTMLElement>(null)

  useLayoutEffect(() => {
    const el = ref.current
    if (el && document.activeElement !== el && el.textContent !== value) el.textContent = value
  }, [value])

  const revert = () => {
    if (ref.current) ref.current.textContent = value
  }

  const onBlur = () => {
    const el = ref.current
    if (!el) return
    const text = (el.textContent ?? '').replace(/\s+/g, ' ').trim()
    if (!allowEmpty && text === '') return revert()
    if (text !== value) onCommit(text)
    else el.textContent = value
  }

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      ref.current?.blur()
    } else if (event.key === 'Escape') {
      // Panelin Esc ile kapanması da dinleniyor; düzenlemeyi iptal ederken panel kapanmasın.
      event.stopPropagation()
      event.preventDefault()
      revert()
      ref.current?.blur()
    }
  }

  return (
    <Tag
      // h2 ve p aynı ref'i alır; JSX'in birleşik etiket tipi bunu tek başına çözemediği için daraltılıyor.
      ref={ref as never}
      className={className}
      contentEditable={editable ? 'plaintext-only' : undefined}
      suppressContentEditableWarning
      spellCheck={false}
      aria-label={editable ? label : undefined}
      data-placeholder={placeholder}
      onBlur={editable ? onBlur : undefined}
      onKeyDown={editable ? onKeyDown : undefined}
    />
  )
}
