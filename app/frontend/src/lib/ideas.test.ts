import { describe, expect, it } from 'vitest'
import { IDEA_POOL, pickIdeas, type Idea } from './ideas.ts'

// Belirlenimli sahte rastgele: verilen diziyi sırayla döndürür.
const sequence = (values: number[]) => {
  let at = 0
  return () => values[at++ % values.length]
}

describe('pickIdeas', () => {
  it('havuzdan üç öneri, üçü de farklı etiketten seçer', () => {
    const picked = pickIdeas(IDEA_POOL, 3, sequence([0, 0, 0]))
    expect(picked).toHaveLength(3)
    expect(new Set(picked.map((idea) => idea.tag)).size).toBe(3)
    for (const idea of picked) expect(IDEA_POOL).toContain(idea)
  })

  it('aynı rastgele dizisiyle aynı sonucu verir ve farklı diziyle değişir', () => {
    const first = pickIdeas(IDEA_POOL, 3, sequence([0.1, 0.5, 0.9]))
    expect(pickIdeas(IDEA_POOL, 3, sequence([0.1, 0.5, 0.9]))).toEqual(first)
    expect(pickIdeas(IDEA_POOL, 3, sequence([0.9, 0.2, 0.4]))).not.toEqual(first)
  })

  it('rastgele 1e çok yakın olsa da sınır dışına taşmaz', () => {
    expect(pickIdeas(IDEA_POOL, 3, () => 0.999999)).toHaveLength(3)
  })

  it('etiket sayısı istenenden azsa elindekini döndürür', () => {
    const pool: Idea[] = [
      { tag: 'a', text: '1' },
      { tag: 'a', text: '2' },
      { tag: 'b', text: '3' },
    ]
    expect(pickIdeas(pool, 3, Math.random)).toHaveLength(2)
    expect(pickIdeas([], 3, Math.random)).toEqual([])
  })
})
