export type Inline = { text: string; strong: boolean }

// Cevap metninde yalnız **kalın** vardır. Akış sürerken kapanmamış "**" görünmesin diye
// `open` açıkken kapanmamış kalın bölüm de kalın sayılır.
export function parseInline(text: string, open = false): Inline[] {
  const parts = text.split('**')
  const result: Inline[] = []
  parts.forEach((part, index) => {
    const isLast = index === parts.length - 1
    const unclosed = index % 2 === 1 && isLast
    if (unclosed && !open) {
      // Çift gelmeyen "**" düz metin kalır.
      const previous = result[result.length - 1]
      if (previous && !previous.strong) previous.text += `**${part}`
      else result.push({ text: `**${part}`, strong: false })
      return
    }
    if (part === '') return
    result.push({ text: part, strong: index % 2 === 1 })
  })
  return result
}

export function splitParagraphs(text: string): string[] {
  return text
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.trim())
    .filter((paragraph) => paragraph !== '')
}
