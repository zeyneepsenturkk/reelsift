# Sonuc 5 - film profili (ham)
Alt kume 6000 film (subset.json, tohum 42; adaylar=50 hedef + 90 listenin ilk 49 sirasi, toplam 3500; kalan 2500 rastgele). Sorgu cozumleme: haiku_out.json. Yargilar ozneldir (tek yargic Sonnet, profil okunmadan, hat gizli); eski yargilar judg.txt/judg_h.txt yeniden kullanildi, yeni cift yargilari judg5.txt.
SAPMA: profil uretimi 24 es zamanli (plan 8); ilk kosu plot sutunu hatasi (pandas .plot) nedeniyle plot'suz uretildi, atilip yeniden uretildi (ilk kosu = 'yalniz TMDB' ablasyonu).

## Profil uretim istatistikleri (plot'lu, nihai)
```
toplam 6000 basari 6000 hata 0 Counter()
benzersiz id 6000
evidence Counter({'rich': 4721, 'thin': 1193, 'insufficient': 85, None: 1})
mood top10 [('tense', 3044), ('tragic', 1185), ('suspenseful', 1123), ('melancholic', 1045), ('bleak', 960), ('playful', 913), ('darkly comic', 759), ('tender', 707), ('somber', 665), ('disturbing', 621)] liste disi 23 [('bittersweet', 13), ('dark', 3), ('uneasy', 2), ('surreal', 1), ('uncomfortable', 1)]
pacing Counter({'unknown': 4726, 'medium': 658, 'fast': 547, 'slow': 69})
girdi tok 8645769 cikti tok 4952644 ort 1440.9615 825.4406666666666
maliyet $ 3.341 film basi 0.0005568164833333333 92374: 51.4
stop Counter({'end_turn': 5996, 'max_tokens': 4}) yeniden deneme Counter({0: 5974, 1: 26})
sure ort sn 4.584216941873232
```

## Bilinen film (50 tarif, alt kume) - profil plot'lu
| varyant | grup | n | R@1 | R@10 | R@50 | R@100 | R@200 | medyan |
|---|---|---|---|---|---|---|---|---|
| K0 onsiralama | hepsi | 50 | 0.60 | 0.88 | 0.94 | 1.00 | 1.00 | 1 |
| K0 onsiralama | bilinen | 22 | 0.82 | 0.95 | 0.95 | 1.00 | 1.00 | 1 |
| K0 onsiralama | az bilinen | 28 | 0.43 | 0.82 | 0.93 | 1.00 | 1.00 | 2 |
| K1 onsiralama | hepsi | 50 | 0.68 | 0.92 | 0.96 | 0.96 | 1.00 | 1 |
| K1 onsiralama | bilinen | 22 | 0.86 | 0.95 | 1.00 | 1.00 | 1.00 | 1 |
| K1 onsiralama | az bilinen | 28 | 0.54 | 0.89 | 0.93 | 0.93 | 1.00 | 1 |
| K0 taban P3b (alt kume) | hepsi | 50 | 0.72 | 0.92 | 0.94 | 1.00 | 1.00 | 1 |
| K0 taban P3b (alt kume) | bilinen | 22 | 0.59 | 0.95 | 0.95 | 1.00 | 1.00 | 1 |
| K0 taban P3b (alt kume) | az bilinen | 28 | 0.82 | 0.89 | 0.93 | 1.00 | 1.00 | 1 |
| K1 taban+profil dense+BM25 | hepsi | 50 | 0.72 | 0.92 | 0.96 | 0.96 | 1.00 | 1 |
| K1 taban+profil dense+BM25 | bilinen | 22 | 0.59 | 0.95 | 1.00 | 1.00 | 1.00 | 1 |
| K1 taban+profil dense+BM25 | az bilinen | 28 | 0.82 | 0.89 | 0.93 | 0.93 | 1.00 | 1 |
| K2 K1 + reranker girdisinde profil | hepsi | 50 | 0.80 | 0.94 | 0.96 | 0.96 | 1.00 | 1 |
| K2 K1 + reranker girdisinde profil | bilinen | 22 | 0.73 | 0.95 | 1.00 | 1.00 | 1.00 | 1 |
| K2 K1 + reranker girdisinde profil | az bilinen | 28 | 0.86 | 0.93 | 0.93 | 0.93 | 1.00 | 1 |

## Ablasyon: profil yalniz TMDB metninden (plot'suz)
| K0 onsiralama | hepsi | 50 | 0.60 | 0.88 | 0.94 | 1.00 | 1.00 | 1 |
| K0 onsiralama | bilinen | 22 | 0.82 | 0.95 | 0.95 | 1.00 | 1.00 | 1 |
| K0 onsiralama | az bilinen | 28 | 0.43 | 0.82 | 0.93 | 1.00 | 1.00 | 2 |
| K1 onsiralama | hepsi | 50 | 0.66 | 0.96 | 0.96 | 0.98 | 1.00 | 1 |
| K1 onsiralama | bilinen | 22 | 0.82 | 1.00 | 1.00 | 1.00 | 1.00 | 1 |
| K1 onsiralama | az bilinen | 28 | 0.54 | 0.93 | 0.93 | 0.96 | 1.00 | 1 |
| K0 taban P3b (alt kume) | hepsi | 50 | 0.72 | 0.92 | 0.94 | 1.00 | 1.00 | 1 |
| K0 taban P3b (alt kume) | bilinen | 22 | 0.59 | 0.95 | 0.95 | 1.00 | 1.00 | 1 |
| K0 taban P3b (alt kume) | az bilinen | 28 | 0.82 | 0.89 | 0.93 | 1.00 | 1.00 | 1 |
| K1 taban+profil dense+BM25 | hepsi | 50 | 0.72 | 0.92 | 0.96 | 0.98 | 1.00 | 1 |
| K1 taban+profil dense+BM25 | bilinen | 22 | 0.59 | 0.95 | 1.00 | 1.00 | 1.00 | 1 |
| K1 taban+profil dense+BM25 | az bilinen | 28 | 0.82 | 0.89 | 0.93 | 0.96 | 1.00 | 1 |
| K2 K1 + reranker girdisinde profil | hepsi | 50 | 0.72 | 0.96 | 0.96 | 0.98 | 1.00 | 1 |
| K2 K1 + reranker girdisinde profil | bilinen | 22 | 0.59 | 1.00 | 1.00 | 1.00 | 1.00 | 1 |
| K2 K1 + reranker girdisinde profil | az bilinen | 28 | 0.82 | 0.93 | 0.93 | 0.96 | 1.00 | 1 |

## Tematik istek basina U/K/A (T2s | +profil | +profil+rr-profil | +mood)
| # | istek | T2s | +profil | +profil+rr | +mood | mood isteği |
|---|---|---|---|---|---|---|
| 1 | kimliğini sorgulayan bir kadının psikolojik geri | 2/3/5 | 1/4/5 | 3/6/1 | 3/6/1 | ['eerie', 'tense'] |
| 2 | küçük bir kasabada geçen, yalnızlık ve yas temal | 3/5/2 | 4/4/2 | 5/4/1 | 5/5/0 | ['contemplative', 'melancholic', 'somber'] |
| 3 | yapay zekânın insanlarla duygusal bağ kurduğu bi | 4/3/3 | 4/3/3 | 7/2/1 | 7/2/1 | ['melancholic', 'tender'] |
| 4 | soygun planı ters giden suç komedisi | 0/7/3 | 2/6/2 | 7/3/0 | 7/3/0 | ['darkly comic', 'playful'] |
| 5 | savaş sonrası travmayla baş eden asker | 9/1/0 | 9/1/0 | 8/2/0 | 8/2/0 | ['somber', 'tragic'] |
| 6 | ıssız bir yerde mahsur kalan bir grup insanın ha | 2/6/2 | 3/6/1 | 4/5/1 | 4/5/1 | ['claustrophobic', 'tense'] |
| 7 | çocukluk arkadaşlarının yıllar sonra buluşması,  | 5/5/0 | 5/5/0 | 8/2/0 | 8/2/0 | ['melancholic', 'nostalgic'] |
| 8 | kasvetli atmosferli, yavaş ilerleyen kuzey ülkes | 2/3/5 | 2/3/5 | 6/2/2 | 6/2/2 | ['bleak', 'gritty', 'somber'] |
| 9 | 90'lardan az bilinen Japon korku filmleri | 5/2/3 | 5/2/3 | 6/4/0 | 6/4/0 | ['disturbing', 'eerie'] |
| 10 | ayrılık sonrası izlenecek umut veren filmler | 2/2/6 | 2/3/5 | 3/3/4 | 3/3/4 | ['hopeful', 'tender', 'uplifting'] |
| 11 | 70'lerden paranoya dolu Amerikan siyasi geriliml | 4/4/2 | 4/5/1 | 7/2/1 | 7/2/1 | ['cynical', 'suspenseful', 'tense'] |
| 12 | küçük bir Fransız kasabasında geçen, sıcak ve ha | 1/3/6 | 1/3/6 | 1/8/1 | 1/8/1 | ['playful', 'warm'] |
| 13 | az bilinen İskandinav bağımsız dramaları, soğuk  | 3/5/2 | 3/6/1 | 6/4/0 | 6/4/0 | ['bleak', 'contemplative', 'intimate'] |
| 14 | 2000'den sonra Kore'den çıkan, gerilimi yüksek i | 2/3/5 | 2/4/4 | 6/3/1 | 6/3/1 | ['disturbing', 'gritty', 'tense'] |
| 15 | yağmurlu bir şehirde geçen melankolik aşk filmle | 1/5/4 | 1/4/5 | 2/7/1 | 2/7/1 | ['melancholic', 'romantic'] |
| 16 | çocuklarla izlenebilecek, az bilinen, hayal gücü | 3/5/2 | 3/5/2 | 5/4/1 | 5/4/1 | ['playful', 'warm', 'whimsical'] |
| 17 | savaş karşıtı duruşu güçlü, 1960 öncesi siyah be | 6/2/2 | 6/2/2 | 7/2/1 | 7/2/1 | ['somber', 'tragic'] |
| 18 | Latin Amerika'dan göçmenlik ve sınır temalı dram | 2/4/4 | 2/4/4 | 5/3/2 | 5/3/2 | ['gritty', 'tragic'] |
| 19 | 80'lerden distopik gelecekte geçen, sisteme karş | 7/2/1 | 7/2/1 | 8/2/0 | 8/2/0 | ['bleak', 'tense'] |
| 20 | İranlı yönetmenlerden, çocukların gözünden anlat | 4/5/1 | 4/5/1 | 5/4/1 | 5/4/1 | ['contemplative', 'intimate', 'tender'] |

Toplam: T2s taban: U67/K75/A58; T2s+profil: U70/K77/A53; T2s+profil+rr-profil: U109/K72/A19; T2s+profil+rr-profil+mood: U109/K73/A18
Ton/atmosfer istekleri (Q2,Q8,Q10,Q13,Q15): T2s taban: U11/K20/A19; T2s+profil: U12/K20/A18; T2s+profil+rr-profil: U22/K20/A8; T2s+profil+rr-profil+mood: U22/K21/A7
ortak top10 (ort) T2s taban vs T2s+profil: 8.9
ortak top10 (ort) T2s+profil vs T2s+profil+rr-profil: 4.3
ortak top10 (ort) T2s+profil+rr-profil vs T2s+profil+rr-profil+mood: 9.8
