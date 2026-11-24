import { describe, expect, it } from 'vitest'
import { StreamFormatError, parseEventStream, parseStreamEvents, toStreamEvent } from './stream.ts'

const encoder = new TextEncoder()

function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
}

async function collect<T>(iterable: AsyncIterable<T>): Promise<T[]> {
  const items: T[] = []
  for await (const item of iterable) items.push(item)
  return items
}

describe('parseEventStream', () => {
  it('olayları adı ve tek satır JSON verisiyle ayırır', async () => {
    const events = await collect(
      parseEventStream(streamOf('event: notice\ndata: {"text":"a"}\n\nevent: text.delta\ndata: {"delta":"b"}\n\n')),
    )
    expect(events).toEqual([
      { event: 'notice', data: '{"text":"a"}' },
      { event: 'text.delta', data: '{"delta":"b"}' },
    ])
  })

  it('iki parçaya bölünen olayı birleştirir (baytın ortasından bile)', async () => {
    const bytes = encoder.encode('event: text.delta\ndata: {"delta":"çay"}\n\n')
    const cut = bytes.indexOf(0xc3) + 1 // "ç" harfinin iki baytı arasından böl
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes.slice(0, cut))
        controller.enqueue(bytes.slice(cut))
        controller.close()
      },
    })
    expect(await collect(parseEventStream(body))).toEqual([{ event: 'text.delta', data: '{"delta":"çay"}' }])
  })

  it('CRLF satır sonlarını ve parça sınırındaki \\r ile \\n ayrılığını doğru okur', async () => {
    const events = await collect(parseEventStream(streamOf('event: notice\r\ndata: {"text":"x"}\r', '\n\r\nevent: notice\r\ndata: {"text":"y"}\r\n\r\n')))
    expect(events.map((event) => event.data)).toEqual(['{"text":"x"}', '{"text":"y"}'])
  })

  it('yorum satırlarını (: ping) ve veri taşımayan blokları yok sayar', async () => {
    const events = await collect(parseEventStream(streamOf(': ping\n\nevent: notice\n: araya yorum\ndata: {"text":"z"}\n\nevent: bos\n\n')))
    expect(events).toEqual([{ event: 'notice', data: '{"text":"z"}' }])
  })

  it('çok satırlı data alanlarını \\n ile birleştirir', async () => {
    const events = await collect(parseEventStream(streamOf('event: notice\ndata: {"text":\ndata: "a"}\n\n')))
    expect(events[0].data).toBe('{"text":\n"a"}')
  })

  it('akış boş satırsız kapanırsa son olayı yine teslim eder', async () => {
    const events = await collect(parseEventStream(streamOf('event: notice\ndata: {"text":"son"}')))
    expect(events).toEqual([{ event: 'notice', data: '{"text":"son"}' }])
  })

  it('boş akışta olay üretmez', async () => {
    expect(await collect(parseEventStream(streamOf()))).toEqual([])
  })
})

describe('toStreamEvent', () => {
  it('bilinen olayı tipli olaya çevirir', () => {
    expect(toStreamEvent({ event: 'text.delta', data: '{"delta":"a"}' })).toEqual({
      event: 'text.delta',
      data: { delta: 'a' },
    })
  })

  it('bilinmeyen olay adını atlar', () => {
    expect(toStreamEvent({ event: 'gelecek.olay', data: '{}' })).toBeNull()
  })

  it('bozuk JSON için hata fırlatır', () => {
    expect(() => toStreamEvent({ event: 'collection', data: '{bozuk' })).toThrow(StreamFormatError)
  })
})

describe('parseStreamEvents', () => {
  it('olayları sırayla tipli olarak verir, bilinmeyeni atlar', async () => {
    const events = await collect(
      parseStreamEvents(streamOf('event: step.start\ndata: {"key":"parse","title":"İsteğini çözüyorum"}\n\nevent: yeni\ndata: {}\n\nevent: error\ndata: {"detail":"d","code":"model_error"}\n\n')),
    )
    expect(events.map((event) => event.event)).toEqual(['step.start', 'error'])
  })

  it('bozuk veri akışı hata ile keser', async () => {
    await expect(collect(parseStreamEvents(streamOf('event: notice\ndata: bozuk\n\n')))).rejects.toBeInstanceOf(StreamFormatError)
  })
})
