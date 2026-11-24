# Faz 3 bağımsız doğrulama (commit 43597b2, 2026-11-17 03:52-04:25)

Ham çıktılar (aynı klasör): faz3-dogrulama-A.txt (kabul), -B.txt (3 değerlendirme), -run.txt (C, D, E, G; betik D:\reelsift-data\_gecici\faz3-dogrulama\run.py), -F.txt (ısındırma/sağlık).

## A kabul
ruff check OK; ruff format 136 dosya biçimli; check 0 sorun; makemigrations "No changes detected"; test: 389 test OK (112 sn).

## B ölçüm tekrarı (builder ile birebir aynı)
- known50 A: RRF %64/%90/%94; A %74/%92/%94 (bilinen %64/%95/%95, az bilinen %82/%89/%93). Koşu 545 sn.
- known50 B: B %78/%94/%94 (bilinen %68/%95/%95, az bilinen %86/%93/%93). 356 sn.
- tone25 genome B: RRF P@10 0.312 nDCG 0.562; B 0.352/0.635 (ortRel 0.607, R@50 0.199). 225 sn.
- /index/eval JSON satırları tablolarla aynı (known50-A/B, tone25-B).
- Not: tone25 B (0.352/0.635) hedef 0.364/0.643'ün altında; ilk ölçüm de aynı sayıyı vermişti.

## C sızıntı
Kod: evaluation.py'de hedef kimliği yalnız `rank_of(item.target_film_id, ...)` ile sıra ölçmede kullanılıyor; arama çağrısına girmiyor (satır 278, 284). Deney (3 tarif, titles boş): Titanic 2 -> 2, Parasite 1 -> 1, Shawshank 1 -> 1. Seçim yanlı: yalnız adlı halde sırası <=3 olan, çok bilinen filmler (oy 21-31 bin). Az bilinen film denenmedi.

## D, E, G
Bkz. faz3-dogrulama-run.txt (tam çıktı).

## F
restart 04:21:37; sunucu 04:22:02 "Agent grafı hazır"; ısınma index 2.5 / embed 45.9 / rerank 71.9 / dummy 20.3 sn; "Arama hazır (140.7 sn)" 04:24:23. Sağlık: ilk ~10 sn bağlantı yok (000), sonra ısınma boyunca hep 200 (0.2-3.2 sn). Sonrası: GPU 3876/8188 MiB, backend 2.81 GiB.
HTTP'den arama çağıran uç yok; sunucu sürecindeki ilk arama süresi DENENEMEDİ.

## H
`docker compose logs db --since 3h`: untracked/PANIC/terminated by signal/could not resize shared memory/out of memory = 0. Başka satırlar: 4x "connection to client lost", 1x "terminating autovacuum process due to administrator command", 2x "test_reelsift already exists", 1x "canceling statement due to user request" (bu pencerede; zararsız görünüyor).
