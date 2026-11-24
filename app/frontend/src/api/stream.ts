import { ApiError } from './errors.ts'
import { buildHeaders, errorFromResponse } from './client.ts'
import type { SendBody, StreamEvent, StreamEventName } from './types.ts'

export type RawEvent = { event: string; data: string }

const KNOWN_EVENTS: ReadonlySet<string> = new Set<StreamEventName>([
  'message.start',
  'step.start',
  'step.done',
  'notice',
  'text.delta',
  'collection',
  'suggestions',
  'message.done',
  'error',
])

// Bir olay bloğunu (boş satırla biten satırlar) ayırır; yorum (`: ping`) ve veri taşımayan bloklar atlanır.
function parseBlock(block: string): RawEvent | null {
  let event = ''
  const data: string[] = []
  for (const line of block.split('\n')) {
    if (line === '' || line.startsWith(':')) continue
    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    let value = colon === -1 ? '' : line.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') event = value
    else if (field === 'data') data.push(value)
  }
  if (!event || data.length === 0) return null
  return { event, data: data.join('\n') }
}

// Saf ayrıştırıcı: baytlar parça parça gelir, bir olay iki parçaya bölünebilir.
export async function* parseEventStream(body: ReadableStream<Uint8Array>): AsyncGenerator<RawEvent> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let heldCarriage = false
  try {
    for (;;) {
      const { done, value } = await reader.read()
      let chunk = done ? decoder.decode() : decoder.decode(value, { stream: true })
      if (heldCarriage) {
        chunk = `\r${chunk}`
        heldCarriage = false
      }
      // Parça sınırında kalan tek "\r" bir sonraki parçadaki "\n" ile çift satır sonu olmasın diye bekletilir.
      if (!done && chunk.endsWith('\r')) {
        chunk = chunk.slice(0, -1)
        heldCarriage = true
      }
      buffer += chunk.replace(/\r\n?/g, '\n')
      let boundary = buffer.indexOf('\n\n')
      while (boundary !== -1) {
        const raw = parseBlock(buffer.slice(0, boundary))
        buffer = buffer.slice(boundary + 2)
        if (raw) yield raw
        boundary = buffer.indexOf('\n\n')
      }
      if (done) break
    }
    // Son olaydan sonra boş satır gelmeden bağlantı kapanırsa yine de teslim edilir.
    const last = parseBlock(buffer)
    if (last) yield last
  } finally {
    reader.releaseLock()
  }
}

export class StreamFormatError extends Error {
  constructor(eventName: string) {
    super(`Bozuk olay verisi: ${eventName}`)
    this.name = 'StreamFormatError'
  }
}

// Bilinmeyen olay adı sessizce atlanır (ileri uyum); bozuk JSON hata sayılır.
export function toStreamEvent(raw: RawEvent): StreamEvent | null {
  if (!KNOWN_EVENTS.has(raw.event)) return null
  try {
    return { event: raw.event, data: JSON.parse(raw.data) } as StreamEvent
  } catch {
    throw new StreamFormatError(raw.event)
  }
}

export async function* parseStreamEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<StreamEvent> {
  for await (const raw of parseEventStream(body)) {
    const event = toStreamEvent(raw)
    if (event) yield event
  }
}

// POST gerektiği için EventSource yerine fetch; `signal` ile iptal edilir (durdur düğmesi).
export async function* streamMessage(
  chatId: number,
  body: SendBody,
  signal: AbortSignal,
): AsyncGenerator<StreamEvent> {
  let response: Response
  try {
    response = await fetch(`/api/chats/${chatId}/messages/stream`, {
      method: 'POST',
      headers: buildHeaders('POST', { 'Content-Type': 'application/json', Accept: 'text/event-stream' }),
      credentials: 'same-origin',
      body: JSON.stringify(body),
      signal,
    })
  } catch (error) {
    if (signal.aborted) throw error
    throw new ApiError(0, 'network_error', '')
  }
  if (!response.ok) throw await errorFromResponse(response)
  if (!response.body) throw new ApiError(response.status, 'server_error', '')
  yield* parseStreamEvents(response.body)
}
