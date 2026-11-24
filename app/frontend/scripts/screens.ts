// Ekran görüntüsü betiği (`npm run screens`): sahte veri kipinde (VITE_MOCK=1) bir geliştirme sunucusu açar,
// 1440x900'de 12 hali ve taslağın dört halini PNG olarak kaydeder, aynı haller için piksel farkı üretir.
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { chromium, type Browser, type BrowserContext, type Page } from '@playwright/test'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const draftFile = join(root, '..', '..', 'tasarim', 'taslak-v2.html')
const out = process.env.SCREENS_OUT ?? 'D:\\reelsift-data\\_gecici\\ekran\\faz5'
const port = Number(process.env.SCREENS_PORT ?? 5174)
const base = process.env.SCREENS_URL ?? `http://127.0.0.1:${port}`
const SIZE = { width: 1440, height: 900 }
const PROMPT = '2015 sonrası, çok bilinmeyen, kasvetli psikolojik gerilimlerden 10 filmlik bir seçki hazırlar mısın?'

const problems: string[] = []

async function startServer(): Promise<ChildProcess | null> {
  if (process.env.SCREENS_URL) return null
  const vite = join(root, 'node_modules', 'vite', 'bin', 'vite.js')
  const child = spawn(process.execPath, [vite, '--port', String(port), '--strictPort', '--host', '127.0.0.1'], {
    cwd: root,
    env: { ...process.env, VITE_MOCK: '1' },
    stdio: 'ignore',
  })
  for (let attempt = 0; attempt < 120; attempt++) {
    try {
      if ((await fetch(base)).ok) return child
    } catch {
      // Sunucu henüz hazır değil.
    }
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  child.kill()
  throw new Error('Geliştirme sunucusu açılmadı')
}

function watch(page: Page, name: string): void {
  page.on('pageerror', (error) => problems.push(`${name}: sayfa hatası: ${error.message}`))
  page.on('console', (message) => {
    if (message.type() !== 'error') return
    const text = message.text()
    // Dış kaynaklar (yazı tipi / afiş) ağ yoksa düşebilir; uygulama hatası değildir ama raporda görünsün.
    problems.push(`${name}: konsol: ${text}`)
  })
}

// Yazı tipleri yüklenmeden ve afişler gelmeden görüntü alınmaz; geçişlerin oturması için kısa bekleme.
async function settle(page: Page, extra = 700): Promise<void> {
  await page.evaluate(async () => {
    await document.fonts.ready
    const pending = [...document.images].filter((image) => !image.complete)
    await Promise.race([
      Promise.all(pending.map((image) => new Promise((resolve) => (image.onload = image.onerror = resolve)))),
      new Promise((resolve) => setTimeout(resolve, 8000)),
    ])
  })
  await page.waitForTimeout(extra)
}

async function shot(page: Page, name: string, extra?: number): Promise<string> {
  // Fare bir öğenin üstünde kalırsa hover hali görüntüye karışır.
  await page.mouse.move(2, 2)
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
  await settle(page, extra)
  const path = join(out, `${name}.png`)
  await page.screenshot({ path })
  console.log(`  ${name}.png`)
  return path
}

async function pixelDiff(browser: Browser, aPath: string, bPath: string, outPath: string): Promise<number> {
  const page = await browser.newPage()
  const result = await page.evaluate(
    async ({ a, b }) => {
      const load = (data: string) =>
        new Promise<HTMLImageElement>((resolve) => {
          const image = new Image()
          image.onload = () => resolve(image)
          image.src = `data:image/png;base64,${data}`
        })
      const [first, second] = await Promise.all([load(a), load(b)])
      const draw = (image: HTMLImageElement) => {
        const canvas = document.createElement('canvas')
        canvas.width = image.width
        canvas.height = image.height
        const ctx = canvas.getContext('2d')!
        ctx.drawImage(image, 0, 0)
        return ctx.getImageData(0, 0, image.width, image.height)
      }
      const left = draw(first)
      const right = draw(second)
      const canvas = document.createElement('canvas')
      canvas.width = left.width
      canvas.height = left.height
      const ctx = canvas.getContext('2d')!
      const diff = ctx.createImageData(left.width, left.height)
      let count = 0
      for (let index = 0; index < left.data.length; index += 4) {
        const delta =
          Math.abs(left.data[index] - right.data[index]) +
          Math.abs(left.data[index + 1] - right.data[index + 1]) +
          Math.abs(left.data[index + 2] - right.data[index + 2])
        const different = delta > 48
        if (different) count++
        diff.data[index] = different ? 255 : right.data[index] * 0.35
        diff.data[index + 1] = different ? 64 : right.data[index + 1] * 0.35
        diff.data[index + 2] = different ? 64 : right.data[index + 2] * 0.35
        diff.data[index + 3] = 255
      }
      ctx.putImageData(diff, 0, 0)
      return { ratio: count / (left.width * left.height), png: canvas.toDataURL('image/png') }
    },
    { a: readFileSync(aPath).toString('base64'), b: readFileSync(bPath).toString('base64') },
  )
  await page.close()
  writeFileSync(outPath, Buffer.from(result.png.split(',')[1], 'base64'))
  return result.ratio
}

async function shootDraft(browser: Browser): Promise<void> {
  console.log('Taslak (referans):')
  const page = await browser.newPage({ viewport: SIZE })
  await page.goto(pathToFileURL(draftFile).href)
  await page.addStyleTag({ content: '.mock{display:none!important}' })
  for (const state of ['new', 'chat', 'open', 'full']) {
    await page.evaluate((target) => {
      location.hash = target
      const button = document.querySelector<HTMLButtonElement>(`.mock button[data-s="${target}"]`)
      button?.click()
    }, state)
    await page.evaluate(() => document.querySelector('.draft-in')?.scrollTo(0, 0))
    await shot(page, `taslak-${state}`, 900)
  }
  await page.close()
}

async function login(page: Page): Promise<void> {
  await page.goto(`${base}/giris`)
  await page.getByLabel('Kullanıcı adı').fill('zeynep')
  await page.getByLabel('Şifre').fill('deneme')
}

async function main(): Promise<void> {
  mkdirSync(out, { recursive: true })
  const server = await startServer()
  const browser = await chromium.launch()
  try {
    await shootDraft(browser)

    console.log('Uygulama (sahte veri):')
    const context: BrowserContext = await browser.newContext({ viewport: SIZE, locale: 'tr-TR' })
    const page = await context.newPage()
    watch(page, 'ana')

    await login(page)
    await shot(page, '01-giris')

    // Yanlış şifre hatası ayrıca denenir; görüntü listesinde yok, yalnız davranış doğrulaması.
    await page.getByLabel('Şifre').fill('yanlis')
    await page.getByRole('button', { name: 'Giriş yap' }).click()
    await page.getByText('Kullanıcı adı ya da şifre yanlış.').waitFor()
    await shot(page, 'ek-giris-hata', 200)
    await page.getByLabel('Şifre').fill('deneme')
    await page.getByRole('button', { name: 'Giriş yap' }).click()

    await page.getByText('Bugün nasıl bir seçki hazırlıyoruz?').waitFor()
    await page.getByText('Gölgede kalmış gerilimler').first().waitFor()
    await shot(page, '02-yeni-sohbet')

    // Sohbet: klavyeyle yaz, Enter ile gönder.
    await page.getByPlaceholder('Örn. karlı kasabalarda').fill(PROMPT)
    await page.keyboard.press('Enter')
    await page.waitForURL(/\/s\/\d+/)
    await page.getByText('arşivi tarıyorum').waitFor()
    await page.waitForTimeout(5200)
    await shot(page, '03-sohbet-calisirken', 100)
    // Metin akarken imleç ve kart (ek görüntü; zamanlama dar, bu yüzden bekleme yok).
    await page.locator('.cursor').waitFor({ timeout: 20000 })
    await shot(page, 'ek-akan-metin', 0)

    await page.locator('.chips .chip').first().waitFor({ timeout: 30000 })
    await page.locator('.app[data-panel="open"]').waitFor()
    await page.waitForTimeout(800)
    await page.locator('.ccard').click()
    await page.waitForTimeout(700)
    await shot(page, '04-sohbet-bitti-panel-kapali')
    await page.locator('.ccard').click()
    await shot(page, '05-taslak-acik', 900)
    await page.getByRole('button', { name: 'Tam ekran' }).click()
    await shot(page, '06-tam-ekran', 900)
    await page.getByRole('button', { name: 'Tam ekran' }).click()
    await page.waitForTimeout(700)
    await page.getByRole('button', { name: 'Kenar çubuğunu daralt' }).click()
    await shot(page, '07-kenar-daraltilmis', 900)
    await page.getByRole('button', { name: 'Kenar çubuğunu daralt' }).click()
    await page.waitForTimeout(700)
    await page.getByRole('button', { name: 'Onayla ve kaydet' }).click()
    await page.getByText('kaydedildi · paylaşılabilir').waitFor()
    await shot(page, '08-onayli', 500)

    await page.getByRole('link', { name: 'tümü ›' }).click()
    await page.getByText('3 seçki').waitFor()
    await shot(page, '09-koleksiyonlarim', 900)

    await page.goto(`${base}/k/karda-kaybolanlar-7k2q`)
    await page.getByText('Zeynep Şentürk').waitFor()
    await shot(page, '10-paylasim', 900)

    await page.goto(`${base}/`)
    await page.getByText('Bugün nasıl bir seçki hazırlıyoruz?').waitFor()
    await page.getByPlaceholder('Örn. karlı kasabalarda').fill('Bu isteğe hata ver')
    await page.keyboard.press('Enter')
    await page.getByText('Bir şey ters gitti, cevabı tamamlayamadım.').waitFor({ timeout: 15000 })
    await shot(page, '11-hata', 600)

    // Taslakla yan yana karşılaştırma: aynı veriler (seed sohbet) ve aynı haller.
    console.log('Karşılaştırma görüntüleri:')
    const cmp = await context.newPage()
    watch(cmp, 'karsilastirma')
    const pairs: [string, string][] = []
    await cmp.goto(`${base}/`)
    await cmp.getByText('Bugün nasıl bir seçki hazırlıyoruz?').waitFor()
    pairs.push(['new', await shot(cmp, 'karsilastirma-new', 900)])
    await cmp.getByText('Gölgede kalmış gerilimler').first().click()
    await cmp.locator('.ccard').waitFor()
    pairs.push(['chat', await shot(cmp, 'karsilastirma-chat', 900)])
    await cmp.locator('.ccard').click()
    pairs.push(['open', await shot(cmp, 'karsilastirma-open', 1200)])
    await cmp.getByRole('button', { name: 'Tam ekran' }).click()
    pairs.push(['full', await shot(cmp, 'karsilastirma-full', 1200)])

    for (const [state, path] of pairs) {
      const ratio = await pixelDiff(browser, join(out, `taslak-${state}.png`), path, join(out, `fark-${state}.png`))
      console.log(`  fark-${state}.png: ${(ratio * 100).toFixed(2)}% piksel farklı`)
    }

    // Orta genişlikler: kenar çubuğu tercihi açıkken panel açılınca kenar çubuğu geçici daralır; hiçbir genişlikte
    // panel düğmeleri ekran dışında kalmaz. 1024x768 ve 960x800 görüntülenir, 900-1200 arası 20 px adımla ölçülür.
    const mid = await browser.newContext({ viewport: { width: 1024, height: 768 }, locale: 'tr-TR' })
    await mid.addInitScript(() => localStorage.setItem('reelsift.mock.user', '1'))
    const midPage = await mid.newPage()
    watch(midPage, 'orta')
    await midPage.goto(`${base}/s/1`)
    await midPage.locator('.ccard').waitFor()
    await midPage.locator('.ccard').click()
    await shot(midPage, '13-orta-1024x768', 1000)
    await midPage.setViewportSize({ width: 960, height: 800 })
    await shot(midPage, '14-orta-960x800', 1000)
    console.log('Ölçüm (panel açık, kenar çubuğu tercihi açık; panel sağ kenarı <= pencere genişliği):')
    let failures = 0
    for (let width = 900; width <= 1200; width += 20) {
      await midPage.setViewportSize({ width, height: 800 })
      await midPage.waitForTimeout(800)
      const m = await midPage.evaluate(() => {
        const close = document.querySelector('[aria-label="Paneli kapat"]')!.getBoundingClientRect()
        const full = document.querySelector('[aria-label="Tam ekran"]')!.getBoundingClientRect()
        const draft = document.querySelector('.draft')!.getBoundingClientRect()
        const title = document.querySelector('.ccard .ct b')?.getBoundingClientRect().width ?? 0
        return { closeRight: close.right, fullLeft: full.left, draftRight: draft.right, title, inner: window.innerWidth }
      })
      const overlay = width < 964
      const ok = m.closeRight <= m.inner && m.draftRight <= m.inner + 0.5 && m.fullLeft >= 0 && (overlay || m.title >= 60)
      if (!ok) failures++
      console.log(`  ${width}: ${ok ? 'tamam' : 'KALDI'} (kapat sağ=${m.closeRight.toFixed(0)}, panel sağ=${m.draftRight.toFixed(0)}, kart başlığı=${m.title.toFixed(0)}px${overlay ? ', üstü kaplar' : ''})`)
    }
    if (failures) problems.push(`ölçüm: ${failures} genişlikte panel taşıyor`)
    await mid.close()

    // Dar ekran: kenar çubuğu daraltılmış başlar, taslak sohbetin üstünü kaplar.
    const narrow = await browser.newContext({ viewport: { width: 820, height: 900 }, locale: 'tr-TR' })
    await narrow.addInitScript(() => localStorage.setItem('reelsift.mock.user', '1'))
    const small = await narrow.newPage()
    watch(small, 'dar')
    await small.goto(`${base}/s/1`)
    await small.locator('.ccard').waitFor()
    await small.locator('.ccard').click()
    await shot(small, '12-dar-ekran-820', 1000)
    await narrow.close()
    await context.close()
  } finally {
    await browser.close()
    server?.kill()
  }

  if (problems.length) {
    console.log(`Konsol/sayfa sorunları (${problems.length}):`)
    for (const problem of problems) console.log(`  ${problem}`)
  } else {
    console.log('Konsolda hata yok.')
  }
}

main().catch((error: unknown) => {
  console.error(error)
  process.exit(1)
})
