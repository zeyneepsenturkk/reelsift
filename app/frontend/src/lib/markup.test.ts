import { describe, expect, it } from 'vitest'
import { parseInline, splitParagraphs } from './markup.ts'

describe('parseInline', () => {
  it('**kalın** bölümlerini ayırır', () => {
    expect(parseInline('a **b** c')).toEqual([
      { text: 'a ', strong: false },
      { text: 'b', strong: true },
      { text: ' c', strong: false },
    ])
  })

  it('işaretleme yoksa tek düz parça verir', () => {
    expect(parseInline('düz metin')).toEqual([{ text: 'düz metin', strong: false }])
  })

  it('HTML gibi görünen metni olduğu gibi (düz metin) bırakır', () => {
    expect(parseInline('<b>x</b> **y**')).toEqual([
      { text: '<b>x</b> ', strong: false },
      { text: 'y', strong: true },
    ])
  })

  it('kapanmamış ** akış sürmüyorsa düz metin kalır', () => {
    expect(parseInline('a **b')).toEqual([{ text: 'a **b', strong: false }])
  })

  it('kapanmamış ** akış sürerken sonuna kadar kalın sayılır', () => {
    expect(parseInline('a **b', true)).toEqual([
      { text: 'a ', strong: false },
      { text: 'b', strong: true },
    ])
  })

  it('boş girdide parça üretmez', () => {
    expect(parseInline('')).toEqual([])
  })
})

describe('splitParagraphs', () => {
  it('boş satırlarla paragraflara böler ve kırpar', () => {
    expect(splitParagraphs(' bir \n\n\n iki ')).toEqual(['bir', 'iki'])
  })

  it('yalnız boşluk içeren metinde paragraf üretmez', () => {
    expect(splitParagraphs('  \n\n ')).toEqual([])
  })
})
