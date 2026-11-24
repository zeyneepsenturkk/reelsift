# Sonuc 4b - Claude Haiku 5.5 ile sorgu cozumleme (ham)
Yargilar ozneldir (tek yargic: Sonnet; yeni ciftler judg_h.txt; eski ciftler judg.txt). n=20.

## T2/T2s istek basina U/K/A
| # | istek | T2 | T2s | T2 filtre |
|---|---|---|---|---|
| 1 | kimliğini sorgulayan bir kadının psikolojik gerilimi | 2/4/4 | 1/4/5 | ['tur'] |
| 2 | küçük bir kasabada geçen, yalnızlık ve yas temalı ağır  | 3/5/2 | 3/4/3 | ['tur'] |
| 3 | yapay zekânın insanlarla duygusal bağ kurduğu bilim kur | 5/3/2 | 4/3/3 | ['tur'] |
| 4 | soygun planı ters giden suç komedisi | 2/4/4 | 1/5/4 | ['tur'] |
| 5 | savaş sonrası travmayla baş eden asker | 9/1/0 | 9/1/0 | ['tur'] |
| 6 | ıssız bir yerde mahsur kalan bir grup insanın hayatta k | 3/5/2 | 3/5/2 | [] |
| 7 | çocukluk arkadaşlarının yıllar sonra buluşması, nostalj | 6/3/1 | 5/4/1 | ['tur'] |
| 8 | kasvetli atmosferli, yavaş ilerleyen kuzey ülkesi polis | 3/2/5 | 2/3/5 | ['ulke', 'tur'] |
| 9 | 90'lardan az bilinen Japon korku filmleri | 5/2/3 | 5/2/3 | ['ymin', 'ymax', 'ulke', 'tur', 'vote'] |
| 10 | ayrılık sonrası izlenecek umut veren filmler | 3/4/3 | 3/4/3 | ['tur'] |
| 11 | 70'lerden paranoya dolu Amerikan siyasi gerilimleri | 4/4/2 | 4/3/3 | ['ymin', 'ymax', 'ulke', 'tur'] |
| 12 | küçük bir Fransız kasabasında geçen, sıcak ve hafif ail | 1/5/4 | 0/3/7 | ['ulke', 'tur'] |
| 13 | az bilinen İskandinav bağımsız dramaları, soğuk ve içe  | 4/6/0 | 3/4/3 | ['ulke', 'tur', 'vote'] |
| 14 | 2000'den sonra Kore'den çıkan, gerilimi yüksek intikam  | 2/4/4 | 2/3/5 | ['ymin', 'ulke', 'tur'] |
| 15 | yağmurlu bir şehirde geçen melankolik aşk filmleri | 2/4/4 | 1/4/5 | ['tur'] |
| 16 | çocuklarla izlenebilecek, az bilinen, hayal gücü yüksek | 3/6/1 | 3/5/2 | ['tur', 'vote'] |
| 17 | savaş karşıtı duruşu güçlü, 1960 öncesi siyah beyaz fil | 6/2/2 | 6/2/2 | ['ymax', 'tur'] |
| 18 | Latin Amerika'dan göçmenlik ve sınır temalı dramalar | 2/3/5 | 2/6/2 | ['tur'] |
| 19 | 80'lerden distopik gelecekte geçen, sisteme karşı çıkan | 7/2/1 | 7/2/1 | ['ymin', 'ymax', 'tur'] |
| 20 | İranlı yönetmenlerden, çocukların gözünden anlatılan sa | 4/2/4 | 4/5/1 | ['ulke', 'tur'] |

Toplam T2 {'U': 76, 'A': 53, 'K': 71}, T2s {'U': 68, 'A': 60, 'K': 72}

## Bilinen film testi tablosu (Haiku)
| varyant | grup | n | R@1 | R@10 | R@50 | R@100 | R@200 | medyan |
|---|---|---|---|---|---|---|---|---|
| P1 onsiralama | hepsi | 50 | 0.56 | 0.80 | 0.92 | 0.94 | 0.94 | 1 |
| P1 onsiralama | bilinen | 22 | 0.82 | 0.95 | 1.00 | 1.00 | 1.00 | 1 |
| P1 onsiralama | az bilinen | 28 | 0.36 | 0.68 | 0.86 | 0.89 | 0.89 | 2 |
| P1 + rerank50 plot | hepsi | 50 | 0.62 | 0.84 | 0.92 | 0.94 | 0.94 | 1 |
| P1 + rerank50 plot | bilinen | 22 | 0.55 | 0.86 | 1.00 | 1.00 | 1.00 | 1 |
| P1 + rerank50 plot | az bilinen | 28 | 0.68 | 0.82 | 0.86 | 0.89 | 0.89 | 1 |
| P1 + rerank50 ov | hepsi | 50 | 0.74 | 0.88 | 0.92 | 0.94 | 0.94 | 1 |
| P1 + rerank50 ov | bilinen | 22 | 0.68 | 0.95 | 1.00 | 1.00 | 1.00 | 1 |
| P1 + rerank50 ov | az bilinen | 28 | 0.79 | 0.82 | 0.86 | 0.89 | 0.89 | 1 |
| P2 onsiralama | hepsi | 50 | 0.66 | 0.88 | 0.94 | 0.94 | 0.96 | 1 |
| P2 onsiralama | bilinen | 22 | 0.86 | 0.95 | 0.95 | 0.95 | 1.00 | 1 |
| P2 onsiralama | az bilinen | 28 | 0.50 | 0.82 | 0.93 | 0.93 | 0.93 | 2 |
| P2 + rerank50 plot | hepsi | 50 | 0.62 | 0.88 | 0.94 | 0.94 | 0.96 | 1 |
| P2 + rerank50 plot | bilinen | 22 | 0.55 | 0.86 | 0.95 | 0.95 | 1.00 | 1 |
| P2 + rerank50 plot | az bilinen | 28 | 0.68 | 0.89 | 0.93 | 0.93 | 0.93 | 1 |
| P2 + rerank50 ov | hepsi | 50 | 0.70 | 0.92 | 0.94 | 0.94 | 0.96 | 1 |
| P2 + rerank50 ov | bilinen | 22 | 0.55 | 0.95 | 0.95 | 0.95 | 1.00 | 1 |
| P2 + rerank50 ov | az bilinen | 28 | 0.82 | 0.89 | 0.93 | 0.93 | 0.93 | 1 |
| P3b(P2,ele) onsiralama | hepsi | 50 | 0.66 | 0.90 | 0.94 | 0.94 | 0.96 | 1 |
| P3b(P2,ele) onsiralama | bilinen | 22 | 0.86 | 0.95 | 0.95 | 0.95 | 1.00 | 1 |
| P3b(P2,ele) onsiralama | az bilinen | 28 | 0.50 | 0.86 | 0.93 | 0.93 | 0.93 | 2 |
| P3b(P2,ele) + rerank50 plot | hepsi | 50 | 0.66 | 0.88 | 0.94 | 0.94 | 0.96 | 1 |
| P3b(P2,ele) + rerank50 plot | bilinen | 22 | 0.64 | 0.86 | 0.95 | 0.95 | 1.00 | 1 |
| P3b(P2,ele) + rerank50 plot | az bilinen | 28 | 0.68 | 0.89 | 0.93 | 0.93 | 0.93 | 1 |
| P3b(P2,ele) + rerank50 ov | hepsi | 50 | 0.72 | 0.92 | 0.94 | 0.94 | 0.96 | 1 |
| P3b(P2,ele) + rerank50 ov | bilinen | 22 | 0.59 | 0.95 | 0.95 | 0.95 | 1.00 | 1 |
| P3b(P2,ele) + rerank50 ov | az bilinen | 28 | 0.82 | 0.89 | 0.93 | 0.93 | 0.93 | 1 |
| P4 P2+filtre (filtre uygulanan sorgu 50/50) + rerank50 plot | hepsi | 50 | 0.62 | 0.88 | 0.94 | 0.94 | 0.96 | 1 |
| P4 P2+filtre (filtre uygulanan sorgu 50/50) + rerank50 plot | bilinen | 22 | 0.55 | 0.86 | 0.95 | 0.95 | 1.00 | 1 |
| P4 P2+filtre (filtre uygulanan sorgu 50/50) + rerank50 plot | az bilinen | 28 | 0.68 | 0.89 | 0.93 | 0.93 | 0.93 | 1 |

G(Haiku): onerilen 100 ad, arsivde bulunan 90; hedef onerilerde: hepsi 25/50, bilinen 22/22, az bilinen 3/28

## Filtre karsilastirmasi (20 tematik) Gemini vs Haiku
| # | Gemini | Haiku |
|---|---|---|
| 1 | {'genres': ['psychological thriller']} | {'genres': ['thriller', 'drama']} |
| 2 | {'genres': ['drama']} | {'genres': ['drama']} |
| 3 | {'genres': ['science fiction', 'drama']} | {'genres': ['science fiction']} |
| 4 | {'genres': ['crime', 'comedy']} | {'genres': ['crime', 'comedy']} |
| 5 | {'genres': ['drama']} | {'genres': ['drama']} |
| 6 | {'genres': ['survival', 'drama', 'adventure']} | {} |
| 7 | {'genres': ['drama']} | {'genres': ['drama']} |
| 8 | {'countries': ['Norway', 'Sweden', 'Denmark', 'Iceland', 'Finland'], 'genres': ['crime', 'thriller', 'mystery']} | {'countries': ['Iceland', 'Norway', 'Sweden', 'Denmark', 'Finland'], 'genres': ['crime', 'mystery', 'thriller']} |
| 9 | {'year_min': 1990, 'year_max': 1999, 'countries': ['Japan'], 'genres': ['horror'], 'max_vote_count': 2000} | {'year_min': 1990, 'year_max': 1999, 'countries': ['Japan'], 'genres': ['horror'], 'max_vote_count': 2000} |
| 10 | {'genres': ['romance', 'drama', 'comedy']} | {'genres': ['drama', 'romance']} |
| 11 | {'year_min': 1970, 'year_max': 1979, 'countries': ['United States'], 'genres': ['thriller']} | {'year_min': 1970, 'year_max': 1979, 'countries': ['United States'], 'genres': ['thriller', 'drama']} |
| 12 | {'countries': ['France'], 'genres': ['comedy', 'family']} | {'countries': ['France'], 'genres': ['comedy', 'family']} |
| 13 | {'countries': ['Norway', 'Sweden', 'Denmark', 'Finland', 'Iceland'], 'genres': ['drama'], 'max_vote_count': 2000} | {'countries': ['Norway', 'Sweden', 'Denmark', 'Finland', 'Iceland'], 'genres': ['drama'], 'max_vote_count': 2000} |
| 14 | {'year_min': 2001, 'countries': ['South Korea'], 'genres': ['thriller', 'revenge']} | {'year_min': 2001, 'countries': ['South Korea'], 'genres': ['thriller', 'revenge']} |
| 15 | {'genres': ['romance', 'drama']} | {'genres': ['romance', 'drama']} |
| 16 | {'genres': ['animation', 'fantasy'], 'max_vote_count': 2000} | {'genres': ['animation', 'family'], 'max_vote_count': 2000} |
| 17 | {'year_max': 1959, 'genres': ['war', 'drama']} | {'year_max': 1959, 'genres': ['war', 'drama']} |
| 18 | {'countries': ['Mexico', 'United States', 'Honduras', 'Guatemala'], 'genres': ['drama']} | {'genres': ['drama']} |
| 19 | {'year_min': 1980, 'year_max': 1989, 'genres': ['science fiction', 'dystopian']} | {'year_min': 1980, 'year_max': 1989, 'genres': ['science fiction']} |
| 20 | {'countries': ['Iran'], 'genres': ['drama']} | {'countries': ['Iran'], 'genres': ['drama']} |

Gemini istek sayisi: {'yil': 5, 'ulke': 8, 'tur': 20, 'vote': 3}; Haiku: {'yil': 5, 'ulke': 7, 'tur': 19, 'vote': 3}
Haiku sureler: ort 4.37, medyan 4.17, max 7.93 sn; girdi ort 573, cikti ort 738 token; istek basi $0.000426, 1000 istek $0.426
effort=medium (ilk 10): sure 4.34 sn / cikti 784; effort=low ayni 10: 3.43 sn / 581
