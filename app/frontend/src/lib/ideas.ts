export type Idea = { tag: string; text: string }

export const IDEA_POOL: Idea[] = [
  { tag: 'tema', text: 'Yas ve yalnızlık üzerine sakin dramlar' },
  { tag: 'tema', text: 'Yağmurlu bir şehirde geçen yalnızlık filmleri' },
  { tag: 'tema', text: 'Taşrada sıkışmışlık üzerine Türk filmleri' },
  { tag: 'tema', text: 'Kardeşler arasındaki kırgınlığı anlatan aile dramları' },
  { tag: 'tema', text: 'Bir gecede geçen, tek mekânlı gerilimler' },
  { tag: 'tema', text: 'Göç ve yersizlik duygusunu anlatan filmler' },
  { tag: 'dönem', text: "70'lerin paranoyak siyasi gerilimleri" },
  { tag: 'dönem', text: "İstanbul'da geçen 1970'ler Türk filmleri" },
  { tag: 'dönem', text: "90'lardan 6 tane Japon korku filmi" },
  { tag: 'dönem', text: "1960'ların Fransız Yeni Dalga filmlerinden 8 tane" },
  { tag: 'keşif', text: 'Az bilinen Güney Kore suç filmleri' },
  { tag: 'keşif', text: 'Az bilinen İran dramları' },
  { tag: 'keşif', text: "Doğu Avrupa'dan kara mizah filmleri" },
  { tag: 'yönetmen', text: "Zeki Demirkubuz'un en iyi 5 filmi" },
  { tag: 'yönetmen', text: "Nuri Bilge Ceylan'ın en iyi 5 filmi" },
  { tag: 'yönetmen', text: "David Lynch'in en karanlık 4 filmi" },
  { tag: 'yönetmen', text: "Hitchcock'un 1950'lerdeki en iyi 5 filmi" },
  { tag: 'yönetmen', text: 'Yılmaz Güney filmleri' },
  { tag: 'oyuncu', text: "Tilda Swinton'ın oynadığı 5 film" },
  { tag: 'oyuncu', text: "Kemal Sunal'ın oynadığı 8 film" },
  { tag: 'oyuncu', text: 'Türkan Şoray filmleri' },
  { tag: 'hava', text: 'Yavaş tempolu, sessiz ve melankolik filmler' },
  { tag: 'hava', text: 'Rüya gibi, tekinsiz atmosferli 8 film' },
  { tag: 'hava', text: 'Sıcak, umut veren yol filmleri' },
]

// Havuzdan `count` öneri seçer; hepsi farklı etiketten gelir. `random` 0 ile 1 arası sayı verir (testte sabitlenir).
export function pickIdeas(pool: Idea[], count: number, random: () => number = Math.random): Idea[] {
  const remaining = pool.slice()
  const picked: Idea[] = []
  while (picked.length < count && remaining.length > 0) {
    const index = Math.min(remaining.length - 1, Math.floor(random() * remaining.length))
    const [idea] = remaining.splice(index, 1)
    picked.push(idea)
    for (let at = remaining.length - 1; at >= 0; at--) {
      if (remaining[at].tag === idea.tag) remaining.splice(at, 1)
    }
  }
  return picked
}
