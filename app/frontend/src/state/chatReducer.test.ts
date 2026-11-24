import { describe, expect, it } from 'vitest'
import type { Chat, Collection, Message, Step, StreamEvent } from '../api/types.ts'
import {
  chatIndicator,
  chatReducer,
  emptyView,
  sessionsReducer,
  unansweredLastMessage,
  type ChatAction,
  type ChatView,
} from './chatReducer.ts'

const message = (patch: Partial<Message> = {}): Message => ({
  id: 1,
  role: 'assistant',
  text: '',
  created_at: '2026-11-16T10:00:00Z',
  steps: [],
  duration_s: null,
  collection_id: null,
  suggestions: [],
  error: null,
  ...patch,
})

const collection = (patch: Partial<Collection> = {}): Collection => ({
  id: 7,
  chat_id: 1,
  title: 'Seçki',
  description: '',
  status: 'draft',
  version: 1,
  films: [],
  stats: { film_count: 0, year_min: null, year_max: null, country_count: 0, avg_vote_count: null },
  share_url: null,
  published_url: null,
  publish_enabled: false,
  approved_at: null,
  updated_at: '2026-11-16T10:00:00Z',
  ...patch,
})

const step = (patch: Partial<Step> = {}): Step => ({
  key: 'search',
  status: 'done',
  title: 'Arşivde dolaştım.',
  detail: '184 aday çıktı.',
  count: 184,
  ...patch,
})

const started = (): ChatView =>
  chatReducer(emptyView('ready'), { type: 'sendStarted', userKey: 'u-1', assistantKey: 'a-1', text: 'merhaba', now: 1000 })

const play = (view: ChatView, ...events: StreamEvent[]): ChatView =>
  events.reduce((current, event, index) => chatReducer(current, { type: 'event', event, now: 2000 + index * 1000 }), view)

const last = (view: ChatView) => view.messages[view.messages.length - 1]

describe('akış olayları', () => {
  it('olağan akışı sırayla işler: adımlar, metin, koleksiyon, öneriler, bitiş', () => {
    let view = started()
    expect(view.streaming).toBe(true)
    expect(view.messages.map((m) => m.role)).toEqual(['user', 'assistant'])

    view = play(
      view,
      { event: 'message.start', data: { user_message: message({ id: 50, role: 'user', text: 'merhaba' }), message_id: 51 } },
      { event: 'step.start', data: { key: 'search', title: 'Arşivde dolaşıyorum' } },
    )
    expect(last(view).id).toBe(51)
    expect(last(view).timeline).toEqual([
      { kind: 'step', step: { key: 'search', status: 'running', title: 'Arşivde dolaşıyorum', detail: '', count: null } },
    ])

    view = play(
      view,
      { event: 'step.done', data: step() },
      { event: 'notice', data: { text: 'Yıl filtresini gevşettim.' } },
      { event: 'text.delta', data: { delta: 'Seçki ' } },
      { event: 'text.delta', data: { delta: 'hazır.' } },
      { event: 'collection', data: collection() },
      { event: 'suggestions', data: { items: ['Daha karanlık olsun'] } },
    )
    expect(last(view).timeline.map((item) => item.kind)).toEqual(['step', 'notice'])
    expect(last(view).text).toBe('Seçki hazır.')
    expect(last(view).collection_id).toBe(7)
    expect(view.collection?.id).toBe(7)

    view = play(view, {
      event: 'message.done',
      data: {
        message: message({ id: 51, text: 'Seçki hazır.', duration_s: 9, collection_id: 7, suggestions: ['Daha karanlık olsun'] }),
        chat: { id: 1, title: 'Yeni başlık', updated_at: '2026-11-16T10:01:00Z' },
      },
    })
    expect(last(view).status).toBe('done')
    expect(last(view).duration_s).toBe(9)
    expect(view.streaming).toBe(false)
    expect(view.title).toBe('Yeni başlık')
    // Canlı çizgideki notice korunur.
    expect(last(view).timeline.some((item) => item.kind === 'notice')).toBe(true)
  })

  it('aynı anahtarlı adım tekrar gelirse (retry) çalışan olan bitirilir', () => {
    let view = started()
    view = play(
      view,
      { event: 'step.start', data: { key: 'retry', title: 'Yeniden arıyorum' } },
      { event: 'step.done', data: step({ key: 'retry', title: 'Yeniden aradım.' }) },
      { event: 'step.start', data: { key: 'retry', title: 'Yeniden arıyorum' } },
    )
    const statuses = last(view).timeline.map((item) => (item.kind === 'step' ? item.step.status : 'notice'))
    expect(statuses).toEqual(['done', 'running'])
    view = play(view, { event: 'step.done', data: step({ key: 'retry', title: 'Bir daha aradım.' }) })
    expect(last(view).timeline.map((item) => (item.kind === 'step' ? item.step.title : ''))).toEqual(['Yeniden aradım.', 'Bir daha aradım.'])
  })

  it('ilk collection olayı paneli açtırır; sonrakiler açtırmaz', () => {
    let view = play(started(), { event: 'collection', data: collection() })
    expect(view.autoOpen).toBe(true)
    expect(view.collectionTick).toBe(1)
    view = chatReducer(view, { type: 'autoOpenHandled' })
    expect(view.autoOpen).toBe(false)
    view = play(view, { event: 'collection', data: collection({ version: 2 }) })
    expect(view.autoOpen).toBe(false)
    expect(view.collectionTick).toBe(2)
    expect(view.collection?.version).toBe(2)
  })

  it('error olayında çalışan adım hataya geçer ve mesaj başarısız olur', () => {
    let view = play(started(), { event: 'step.start', data: { key: 'parse', title: 'İsteğini çözüyorum' } })
    view = play(view, { event: 'error', data: { detail: 'x', code: 'model_error' } })
    const item = last(view).timeline[0]
    expect(item.kind === 'step' && item.step.status).toBe('error')
    expect(last(view).status).toBe('failed')
    expect(last(view).error?.code).toBe('model_error')
    expect(view.streaming).toBe(false)
  })

  it('bozuk girdi: akıştaki mesaj yokken gelen olay görünümü değiştirmez', () => {
    const idle: ChatView = emptyView('ready')
    const next = chatReducer(idle, { type: 'event', event: { event: 'text.delta', data: { delta: 'x' } }, now: 1 })
    expect(next).toEqual(idle)
  })

  it('bozuk girdi: karşılığı olmayan step.done sona eklenir (kayıp olmaz)', () => {
    const view = play(started(), { event: 'step.done', data: step() })
    expect(last(view).timeline).toHaveLength(1)
  })

  it('message.done süre vermezse ölçülen süreyi kullanır', () => {
    const view = play(started(), {
      event: 'message.done',
      data: { message: message({ duration_s: null }), chat: { id: 1, title: 't', updated_at: 'x' } },
    })
    expect(last(view).duration_s).toBe(1) // now=2000, başlangıç=1000
  })
})

describe('sıra ve kalıcılık', () => {
  it('collection olayı metinden ÖNCE gelirse de koleksiyon ve mesaj bağı kurulur, metin sonra eklenir', () => {
    let view = play(started(), { event: 'collection', data: collection() })
    expect(last(view).text).toBe('')
    expect(last(view).collection_id).toBe(7)
    expect(view.collection?.id).toBe(7)
    expect(view.autoOpen).toBe(true)
    view = play(view, { event: 'text.delta', data: { delta: 'Seçki hazır.' } })
    expect(last(view).text).toBe('Seçki hazır.')
    expect(last(view).collection_id).toBe(7)
  })

  it('kayıtlı key:notice adımı bilgi satırı olarak yüklenir', () => {
    const chat: Chat = {
      id: 3,
      title: 't',
      updated_at: 'x',
      collection: null,
      messages: [message({ steps: [step(), step({ key: 'notice', title: '', detail: 'Yıl filtresini gevşettim.', count: null })] })],
    }
    const view = chatReducer(emptyView('loading'), { type: 'loaded', chat })
    expect(view.messages[0].timeline.map((item) => item.kind)).toEqual(['step', 'notice'])
    expect(view.messages[0].timeline[1]).toEqual({ kind: 'notice', text: 'Yıl filtresini gevşettim.' })
  })

  it('düğmeden gelen action kullanıcı mesajında saklanır (Tekrar dene kaybetmesin)', () => {
    const withAction = chatReducer(emptyView('ready'), {
      type: 'sendStarted',
      userKey: 'u',
      assistantKey: 'a',
      text: 'Yeniden araştır',
      action: { type: 'research' },
      now: 1,
    })
    expect(withAction.messages[0].action).toEqual({ type: 'research' })
    const plain = chatReducer(emptyView('ready'), { type: 'sendStarted', userKey: 'u', assistantKey: 'a', text: 'x', now: 1 })
    expect(plain.messages[0].action).toBeUndefined()
  })
})

describe('durdurma, hata ve yeniden deneme', () => {
  it('stopped: çalışan adımlar düşer, mesaj durduruldu olur', () => {
    let view = play(started(), { event: 'step.start', data: { key: 'parse', title: 'İsteğini çözüyorum' } }, { event: 'text.delta', data: { delta: 'yarım' } })
    view = chatReducer(view, { type: 'stopped', now: 5000 })
    expect(last(view).status).toBe('stopped')
    expect(last(view).timeline).toEqual([])
    expect(last(view).text).toBe('yarım')
    expect(view.streaming).toBe(false)
  })

  it('failed (ağ kopması) error olayı gibi işlenir', () => {
    const view = chatReducer(started(), { type: 'failed', detail: '', code: 'network_error', now: 3000 })
    expect(last(view).status).toBe('failed')
    expect(last(view).error?.code).toBe('network_error')
  })

  it('discardFailed hatalı cevabı ve onu doğuran kullanıcı mesajını kaldırır', () => {
    let view = chatReducer(started(), { type: 'failed', detail: '', code: 'x', now: 1 })
    view = chatReducer(view, { type: 'discardFailed' })
    expect(view.messages).toEqual([])
  })

  it('discardFailed başarısız olmayan son mesajı bırakır', () => {
    const view = started()
    expect(chatReducer(view, { type: 'discardFailed' })).toBe(view)
  })
})

describe('yükleme', () => {
  const chat: Chat = {
    id: 3,
    title: 'Sohbet',
    updated_at: 'x',
    collection: collection(),
    messages: [message({ id: 1, role: 'user', text: 'a' }), message({ id: 2, steps: [step()], text: 'b', duration_s: 14 })],
  }

  it('geçmiş mesajları bitmiş halde, panel kendiliğinden açılmadan yükler', () => {
    const view = chatReducer(emptyView('loading'), { type: 'loaded', chat })
    expect(view.phase).toBe('ready')
    expect(view.messages.map((m) => m.status)).toEqual(['done', 'done'])
    expect(view.messages[1].timeline).toHaveLength(1)
    expect(view.autoOpen).toBe(false)
    expect(view.collection?.id).toBe(7)
  })

  it('hata kaydı olan eski mesaj başarısız görünür', () => {
    const failed: Chat = { ...chat, messages: [message({ error: { detail: 'd', code: 'model_error' } })] }
    expect(chatReducer(emptyView('loading'), { type: 'loaded', chat: failed }).messages[0].status).toBe('failed')
  })

  it('loadFailed 404 için missing, diğerleri için error olur', () => {
    expect(chatReducer(emptyView('loading'), { type: 'loadFailed', missing: true }).phase).toBe('missing')
    expect(chatReducer(emptyView('loading'), { type: 'loadFailed', missing: false }).phase).toBe('error')
  })

  it('hazır görünüm yeniden yüklemede sıfırlanmaz', () => {
    const ready = chatReducer(emptyView('loading'), { type: 'loaded', chat })
    expect(chatReducer(ready, { type: 'loadStarted' })).toBe(ready)
  })
})

describe('cevapsız kalan son kullanıcı mesajı', () => {
  const chatEndingWith = (...messages: Message[]): Chat => ({
    id: 3,
    title: 'Sohbet',
    updated_at: 'x',
    collection: null,
    messages,
  })
  const open = (...messages: Message[]) => chatReducer(emptyView('loading'), { type: 'loaded', chat: chatEndingWith(...messages) })
  const asked = message({ id: 1, role: 'user', text: 'Karlı kasabalar' })
  const answered = message({ id: 2, role: 'assistant', text: 'Hazır.' })

  it('yeniden açılan sohbette son mesaj kullanıcınınsa cevapsız sayılır', () => {
    expect(unansweredLastMessage(open(asked))?.text).toBe('Karlı kasabalar')
    expect(unansweredLastMessage(open(asked, answered, message({ id: 3, role: 'user', text: 'Daha karanlık' })))?.text).toBe(
      'Daha karanlık',
    )
  })

  it('cevaplanmış, hatalı ya da boş sohbet cevapsız sayılmaz', () => {
    expect(unansweredLastMessage(open(asked, answered))).toBeNull()
    expect(unansweredLastMessage(open(asked, message({ id: 2, error: { detail: 'd', code: 'model_error' } })))).toBeNull()
    expect(unansweredLastMessage(open())).toBeNull()
  })

  it('akış sürerken, yüklenirken ve boş metinde cevapsız sayılmaz', () => {
    expect(unansweredLastMessage(started())).toBeNull()
    expect(unansweredLastMessage(emptyView('loading'))).toBeNull()
    expect(unansweredLastMessage(open(message({ id: 1, role: 'user', text: '   ' })))).toBeNull()
  })

  it('discardUnanswered yalnız cevapsız son kullanıcı mesajını kaldırır', () => {
    const view = open(asked, answered, message({ id: 3, role: 'user', text: 'Daha karanlık' }))
    expect(chatReducer(view, { type: 'discardUnanswered' }).messages.map((m) => m.id)).toEqual([1, 2])

    const done = open(asked, answered)
    expect(chatReducer(done, { type: 'discardUnanswered' })).toBe(done)
    const running = started()
    expect(chatReducer(running, { type: 'discardUnanswered' })).toBe(running)
  })

  it('kaldırıp aynı metni göndermek mesajı çoğaltmaz', () => {
    let view = chatReducer(open(asked), { type: 'discardUnanswered' })
    view = chatReducer(view, { type: 'sendStarted', userKey: 'u-9', assistantKey: 'a-9', text: 'Karlı kasabalar', now: 5 })
    expect(view.messages.map((m) => [m.role, m.text])).toEqual([
      ['user', 'Karlı kasabalar'],
      ['assistant', ''],
    ])
    expect(unansweredLastMessage(view)).toBeNull()
  })
})

describe('sessionsReducer', () => {
  it('sohbetleri kimliğe göre ayrı tutar', () => {
    const action = (chatId: number, inner: ChatAction) => ({ type: 'chat' as const, chatId, action: inner })
    let state = sessionsReducer({}, { type: 'create', chatId: 1, title: 'a' })
    state = sessionsReducer(state, { type: 'create', chatId: 2, title: 'b' })
    state = sessionsReducer(state, action(1, { type: 'sendStarted', userKey: 'u', assistantKey: 'a', text: 'x', now: 1 }))
    expect(state[1].messages).toHaveLength(2)
    expect(state[2].messages).toHaveLength(0)
  })
})

describe('kenar çubuğu göstergesi', () => {
  const done = (): StreamEvent => ({
    event: 'message.done',
    data: {
      message: message({ id: 51, text: 'Hazır.' }),
      chat: { id: 1, title: 'Başlık', updated_at: '2026-11-16T10:01:00Z' },
    },
  })

  it('akış sürerken halka, sohbet yokken ya da boştayken gösterge yok', () => {
    expect(chatIndicator(undefined)).toBeNull()
    expect(chatIndicator(emptyView('ready'))).toBeNull()
    expect(chatIndicator(started())).toBe('working')
  })

  it('cevap bitince görülmemiş işareti kalır; sohbet açılınca (markSeen) kalkar', () => {
    const view = play(started(), done())
    expect(view.unseen).toBe(true)
    expect(chatIndicator(view)).toBe('unseen')
    const seen = chatReducer(view, { type: 'markSeen' })
    expect(seen.unseen).toBe(false)
    expect(chatIndicator(seen)).toBeNull()
    expect(chatReducer(seen, { type: 'markSeen' })).toBe(seen)
  })

  it('hatayla biten cevap da görülmemiş sayılır', () => {
    const view = chatReducer(started(), { type: 'failed', detail: '', code: 'network_error', now: 3000 })
    expect(chatIndicator(view)).toBe('unseen')
  })

  it('kullanıcının durdurduğu cevapta nokta çıkmaz', () => {
    const view = chatReducer(started(), { type: 'stopped', now: 3000 })
    expect(view.unseen).toBe(false)
    expect(chatIndicator(view)).toBeNull()
  })

  it('yeni istek başlayınca nokta kalkar, halka gelir', () => {
    const unseen = play(started(), done())
    const view = chatReducer(unseen, {
      type: 'sendStarted', userKey: 'u-2', assistantKey: 'a-2', text: 'bir daha', now: 5000,
    })
    expect(view.unseen).toBe(false)
    expect(chatIndicator(view)).toBe('working')
  })

  it('sohbet başka sohbetin durumunu etkilemez (sessionsReducer)', () => {
    let state = sessionsReducer({}, { type: 'create', chatId: 1, title: 'A' })
    state = sessionsReducer(state, { type: 'create', chatId: 2, title: 'B' })
    state = sessionsReducer(state, {
      type: 'chat', chatId: 1, action: { type: 'sendStarted', userKey: 'u', assistantKey: 'a', text: 'x', now: 1 },
    })
    expect(chatIndicator(state[1])).toBe('working')
    expect(chatIndicator(state[2])).toBeNull()
  })
})
