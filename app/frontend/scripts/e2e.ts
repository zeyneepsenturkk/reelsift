// Gerçek backend'e karşı uçtan uca deneme (`npm run e2e`); sahte veri KAPALI (VITE_MOCK verilmez).
// Ön koşul: backend (ör. rs-agent yığını, :8001) ve arayüz geliştirme sunucusu (:5174, VITE_API_PROXY ile) açık.
// Ortam değişkenleri (şifre ve komutlar depoya yazılmaz, çalıştıran verir):
//   E2E_USER, E2E_PASSWORD  var olan deneme kullanıcısı
//   E2E_SEED_CMD            kullanıcıya bağlı taslak koleksiyon kurup son satıra {"chat_id","collection_id"} JSON'u basan komut
//   E2E_URL (varsayılan http://127.0.0.1:5174), E2E_OUT (ekran görüntüleri), E2E_MODEL_WAIT_MS (hata akışı bekleme sınırı)
// Giriş ucunda IP başına dakikada 10 deneme sınırı vardır; betik son adımda sınırı bilerek aşar, yeniden çalıştırmadan önce 1 dk bekle.
import { execSync } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { chromium, type Browser, type BrowserContext, type Page, type Response } from '@playwright/test'

const base = process.env.E2E_URL ?? 'http://127.0.0.1:5174'
const out = process.env.E2E_OUT ?? 'D:\\reelsift-data\\_gecici\\ekran\\faz6'
const username = process.env.E2E_USER ?? ''
const password = process.env.E2E_PASSWORD ?? ''
const seedCommand = process.env.E2E_SEED_CMD ?? ''
const modelWait = Number(process.env.E2E_MODEL_WAIT_MS ?? 90_000)
const SIZE = { width: 1440, height: 900 }
const PIXEL = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
  'base64',
)

// Beklenen hata cevapları (yol deseni + durum). Bunların dışındaki her >= 400 cevap hata sayılır.
const EXPECTED: { method: string; path: RegExp; status: number; why: string }[] = [
  { method: 'GET', path: /^\/api\/auth\/me$/, status: 401, why: 'girişsiz açılış' },
  { method: 'POST', path: /^\/api\/auth\/login$/, status: 401, why: 'yanlış şifre' },
  { method: 'POST', path: /^\/api\/auth\/login$/, status: 429, why: 'deneme sınırı' },
  { method: 'GET', path: /^\/api\/share\/yok-boyle-bir-anahtar$/, status: 404, why: 'yanlış paylaşım anahtarı' },
  { method: 'POST', path: /^\/api\/chats$/, status: 401, why: 'oturum düştü' },
]

const unexpected: string[] = []
const consoleErrors: string[] = []
const seen: string[] = []
let failures = 0

function watch(page: Page, label: string): void {
  page.on('pageerror', (error) => consoleErrors.push(`${label}: sayfa hatası: ${error.message}`))
  page.on('console', (message) => {
    if (message.type() !== 'error') return
    // Tarayıcı her >= 400 cevap için "Failed to load resource" yazar; cevaplar aşağıda ayrıca denetlenir.
    if (message.text().startsWith('Failed to load resource')) return
    consoleErrors.push(`${label}: konsol: ${message.text()}`)
  })
  page.on('response', (response: Response) => {
    const url = new URL(response.url())
    if (!url.pathname.startsWith('/api/') || response.status() < 400) return
    const method = response.request().method()
    const hit = EXPECTED.find((item) => item.method === method && item.path.test(url.pathname) && item.status === response.status())
    const line = `${label}: ${method} ${url.pathname} -> ${response.status()}`
    if (hit) seen.push(`${line} (beklenen: ${hit.why})`)
    else unexpected.push(line)
  })
}

async function step(name: string, run: () => Promise<void>): Promise<void> {
  try {
    await run()
    console.log(`GEÇTİ  ${name}`)
  } catch (error) {
    failures++
    console.log(`KALDI  ${name}\n       ${error instanceof Error ? error.message.split('\n')[0] : String(error)}`)
  }
}

function check(condition: boolean, message: string): void {
  if (!condition) throw new Error(message)
}

async function shot(page: Page, name: string): Promise<void> {
  await page.mouse.move(2, 2)
  await page.waitForTimeout(700)
  await page.screenshot({ path: join(out, `${name}.png`) })
}

async function newContext(browser: Browser, label: string): Promise<{ context: BrowserContext; page: Page }> {
  const context = await browser.newContext({ viewport: SIZE, locale: 'tr-TR', baseURL: base })
  // Afişler dış adresten gelir; ağdan bağımsız olsun diye sabit bir görselle karşılanır.
  await context.route('https://image.tmdb.org/**', (route) => route.fulfill({ status: 200, contentType: 'image/png', body: PIXEL }))
  const page = await context.newPage()
  watch(page, label)
  return { context, page }
}

// Yazı tipi gibi dış kaynaklar `load` olayını geciktirebilir; sayfa DOM'u hazır olunca devam edilir.
async function go(page: Page, path: string): Promise<void> {
  await page.goto(path, { waitUntil: 'domcontentloaded' })
}

async function logIn(page: Page, secret = password): Promise<void> {
  await page.getByLabel('Kullanıcı adı').fill(username)
  await page.getByLabel('Şifre').fill(secret)
  await page.getByRole('button', { name: 'Giriş yap' }).click()
}

async function api<T>(page: Page, path: string): Promise<T> {
  return page.evaluate(async (target) => (await fetch(target, { credentials: 'same-origin' })).json(), `/api${path}`) as Promise<T>
}

async function main(): Promise<void> {
  if (!username || !password || !seedCommand) {
    throw new Error('E2E_USER, E2E_PASSWORD ve E2E_SEED_CMD verilmeli (başlık yorumuna bak).')
  }
  mkdirSync(out, { recursive: true })
  const browser = await chromium.launch()
  const { context, page } = await newContext(browser, 'ana')
  let seeded = { chat_id: 0, collection_id: 0 }
  let shareUrl = ''

  await step('1. girişsiz "/" -> /giris', async () => {
    await go(page, '/')
    await page.waitForURL('**/giris')
    await page.getByRole('button', { name: 'Giriş yap' }).waitFor()
    await shot(page, '01-giris')
  })

  await step('1. yanlış şifre -> hata mesajı, sayfada kalır', async () => {
    await logIn(page, 'kesinlikle-yanlis-sifre')
    await page.getByRole('alert').filter({ hasText: 'Kullanıcı adı ya da şifre yanlış.' }).waitFor()
    check(new URL(page.url()).pathname === '/giris', 'giriş sayfasından ayrıldı')
    await shot(page, '02-yanlis-sifre')
  })

  await step('1. doğru giriş -> "/", oturum çerezi HttpOnly, CSRF çerezi okunabilir', async () => {
    await logIn(page)
    await page.waitForURL((url) => url.pathname === '/')
    await page.getByRole('heading', { name: /Bugün nasıl bir seçki/ }).waitFor()
    const cookies = await context.cookies()
    const session = cookies.find((cookie) => cookie.name === 'sessionid')
    const csrf = cookies.find((cookie) => cookie.name === 'csrftoken')
    check(session?.httpOnly === true && session.sameSite === 'Lax', 'oturum çerezi HttpOnly + Lax değil')
    check(csrf !== undefined && csrf.httpOnly === false, 'csrftoken çerezi okunabilir değil')
    check(!(await page.evaluate(() => document.cookie)).includes('sessionid'), 'oturum çerezi JS ile okunabiliyor')
    await shot(page, '03-ana')
  })

  let firstChatPath = ''
  await step('2-3. mesaj: sohbet açılır, kenar çubuğunda görünür, akış hata ile biter, arayüz kilitlenmez', async () => {
    await page.getByRole('textbox').first().fill('Karlı kasabalarda geçen polisiyeler')
    await page.keyboard.press('Enter')
    await page.waitForURL(/\/s\/\d+$/)
    firstChatPath = new URL(page.url()).pathname
    await page.locator('.side .list a', { hasText: /\S/ }).first().waitFor()
    await page.locator('.errbox').waitFor({ timeout: modelWait })
    await page.getByRole('button', { name: 'Tekrar dene' }).waitFor()
    await shot(page, '04-akis-hatasi')
    check((await page.locator('.me').count()) === 1, 'kullanıcı mesajı bir tane olmalı')
    await page.getByRole('button', { name: 'Tekrar dene' }).click()
    // "Tekrar dene" başarısız çifti ekrandan kaldırıp aynı metni yeni mesaj olarak gönderir: ekranda hâlâ tek kullanıcı balonu.
    const chatId = firstChatPath.split('/').pop()
    await page.waitForFunction(
      async (id) => {
        const chat = (await (await fetch(`/api/chats/${id}`)).json()) as { messages: { role: string }[] }
        return chat.messages.filter((message) => message.role === 'user').length === 2
      },
      chatId,
      { timeout: modelWait },
    )
    await page.locator('.errbox').waitFor({ timeout: modelWait })
    check((await page.locator('.me').count()) === 1, 'tekrar denemede kullanıcı balonu çoğaldı')
    await page.getByRole('button', { name: 'Gönder' }).waitFor()
    check(await page.getByRole('textbox').first().isEnabled(), 'yazma alanı kilitli kaldı')
    await shot(page, '05-tekrar-dene-hata')
  })

  await step('2. sayfa yenilenince oturum ve sohbet listesi yerinde', async () => {
    await page.reload()
    await page.locator('.side .user').waitFor()
    check(new URL(page.url()).pathname === firstChatPath, 'yol değişti')
    await page.locator(`.side .list a[href="${firstChatPath}"]`).waitFor()
    await page.locator('.me').first().waitFor()
    const chat = await api<{ messages: { role: string }[] }>(page, `/chats/${firstChatPath.split('/').pop()}`)
    check(chat.messages.filter((message) => message.role === 'user').length === 2, 'sunucuda iki kullanıcı mesajı olmalı')
    await shot(page, '06-yenilendi')
  })

  await step('4. taslak: başlık düzenle, film çıkar, onayla -> paylaşım linki, salt okunur', async () => {
    seeded = JSON.parse(execSync(seedCommand, { encoding: 'utf8', timeout: 120_000 }).trim().split('\n').pop() ?? '{}')
    check(seeded.chat_id > 0, 'tohum verisi kurulamadı')
    await go(page, `/s/${seeded.chat_id}`)
    await page.locator('.ccard').click()
    const title = page.getByLabel('Seçki başlığı')
    await title.waitFor()
    check((await page.locator('.films .card').count()) === 4, 'dört film bekleniyordu')
    await title.click()
    await page.keyboard.press('Control+A')
    await page.keyboard.type('E2E düzenlenmiş başlık')
    await page.keyboard.press('Enter')
    await page.locator('.saved[data-on="true"]').waitFor()
    await page.getByRole('button', { name: /Kallio Kışı taslaktan çıkar/ }).click()
    await page.waitForFunction(() => document.querySelectorAll('.films .card').length === 3)
    await shot(page, '07-taslak-duzenlendi')
    // Sunucuya gerçekten yazıldı mı: yenile ve sunucudan oku.
    const draft = await api<{ title: string; films: unknown[]; status: string }>(page, `/collections/${seeded.collection_id}`)
    check(draft.title === 'E2E düzenlenmiş başlık' && draft.films.length === 3 && draft.status === 'draft', 'sunucudaki taslak güncel değil')
    await page.getByRole('button', { name: 'Onayla ve kaydet' }).click()
    await page.getByText('kaydedildi · paylaşılabilir').waitFor()
    const approved = await api<{ status: string; share_url: string | null }>(page, `/collections/${seeded.collection_id}`)
    check(approved.status === 'approved' && /^\/k\/[\w-]+$/.test(approved.share_url ?? ''), 'onay sonrası paylaşım linki yok')
    shareUrl = approved.share_url ?? ''
    check((await page.locator('.films .x').count()) === 0, 'onaylı koleksiyonda çıkar düğmesi var')
    check((await page.getByLabel('Seçki başlığı').count()) === 0, 'onaylı başlık hâlâ düzenlenebilir')
    await shot(page, '08-onayli')
  })

  await step('4. /koleksiyonlar ve /koleksiyon/:id: onaylı koleksiyon listede, salt okunur', async () => {
    await go(page, '/koleksiyonlar')
    await page.locator(`a[href="/koleksiyon/${seeded.collection_id}"]`).first().waitFor()
    await page.locator('.coll-grid .ccard').first().waitFor()
    check((await page.locator('.coll-grid .ccard').count()) === 1, 'tek onaylı koleksiyon bekleniyordu')
    await shot(page, '09-koleksiyonlarim')
    await page.locator(`.coll-grid a[href="/koleksiyon/${seeded.collection_id}"]`).click()
    await page.getByText('kaydedildi · paylaşılabilir').waitFor()
    check((await page.locator('.films .x').count()) === 0, 'salt okunur sayfada çıkar düğmesi var')
    await shot(page, '10-koleksiyon-sayfasi')
  })

  await step('5. paylaşım linki girişsiz yeni bağlamda açılır; kimlik alanı yok', async () => {
    const guest = await newContext(browser, 'misafir')
    const identityCalls: string[] = []
    guest.page.on('request', (request) => {
      if (new URL(request.url()).pathname === '/api/auth/me') identityCalls.push(request.url())
    })
    await go(guest.page, shareUrl)
    await guest.page.getByRole('heading', { name: 'E2E düzenlenmiş başlık' }).waitFor()
    check(identityCalls.length === 0, `paylaşım sayfası /api/auth/me çağırdı (${identityCalls.length})`)
    check((await guest.page.locator('.side').count()) === 0, 'paylaşım sayfasında kenar çubuğu var')
    check((await guest.page.locator('.films .card').count()) === 3, 'paylaşımda üç film bekleniyordu')
    check(!(await guest.context.cookies()).some((cookie) => cookie.name === 'sessionid'), 'misafirde oturum çerezi oluştu')
    const shared = await api<Record<string, unknown>>(guest.page, `/share/${shareUrl.split('/').pop()}`)
    const text = JSON.stringify(shared)
    check(!('id' in shared) && !('chat_id' in shared) && !text.includes(username), 'paylaşım cevabı kimlik taşıyor')
    await shot(guest.page, '11-paylasim')
    await go(guest.page, '/k/yok-boyle-bir-anahtar')
    await guest.page.getByText('Bu seçki bulunamadı').waitFor()
    await shot(guest.page, '12-paylasim-404')
    await guest.context.close()
  })

  await step('3. oturum düşünce (çerez silindi) korumalı istek -> /giris, yeniden giriş çalışır', async () => {
    await go(page, '/')
    await page.getByRole('textbox').first().waitFor()
    await context.clearCookies({ name: 'sessionid' })
    await page.getByRole('textbox').first().fill('oturum düştü denemesi')
    await page.keyboard.press('Enter')
    await page.waitForURL('**/giris')
    await shot(page, '13-oturum-dustu')
    await logIn(page)
    await page.waitForURL((url) => url.pathname !== '/giris')
    await page.locator('.side .user').waitFor()
  })

  await step('6. çıkış -> /giris; geri tuşu korumalı sayfayı açmaz', async () => {
    await go(page, '/koleksiyonlar')
    await page.locator('.side .user').click()
    await page.getByRole('menuitem', { name: 'Çıkış yap' }).click()
    await page.waitForURL('**/giris')
    await page.goBack()
    await page.waitForTimeout(800)
    check(new URL(page.url()).pathname === '/giris', `geri tuşuyla ${new URL(page.url()).pathname} açıldı`)
    check((await page.locator('.side').count()) === 0, 'korumalı kabuk göründü')
    check((await api<{ code: string }>(page, '/auth/me')).code === 'not_authenticated', 'sunucu oturumu hâlâ açık')
    await shot(page, '14-cikis')
  })

  await step('giriş ucu: deneme sınırı aşılınca sade Türkçe mesaj (429)', async () => {
    let shown = false
    for (let attempt = 0; attempt < 14 && !shown; attempt++) {
      await go(page, '/giris')
      await logIn(page, `yanlis-${attempt}`)
      const alert = page.getByRole('alert')
      await alert.waitFor()
      shown = ((await alert.textContent()) ?? '').includes('Çok fazla deneme yaptın')
    }
    check(shown, 'deneme sınırı mesajı görünmedi')
    await shot(page, '15-deneme-siniri')
  })

  await browser.close()
  console.log(`\nBeklenen hata cevapları (${seen.length}):`)
  for (const line of seen) console.log(`  ${line}`)
  console.log(`Beklenmeyen >= 400 cevap: ${unexpected.length}`)
  for (const line of unexpected) console.log(`  ${line}`)
  console.log(`Konsol/sayfa hatası: ${consoleErrors.length}`)
  for (const line of consoleErrors) console.log(`  ${line}`)
  if (failures > 0 || unexpected.length > 0 || consoleErrors.length > 0) process.exitCode = 1
}

main().catch((error: unknown) => {
  console.error(error)
  process.exit(1)
})
