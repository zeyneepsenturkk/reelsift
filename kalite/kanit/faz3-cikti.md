# Faz 3 ham çıktı (builder)

## Kabul komutları (up -d --build: yalnız frontend npm ci hatası; backend imajı önceden başarıyla kuruldu, bkz. rapor)
```
### docker compose up -d --build
   8 |     COPY . .
--------------------
target frontend: failed to solve: process "/bin/sh -c npm ci" did not complete successfully: exit code: 1
### docker compose exec -T backend ruff check .
All checks passed!
### docker compose exec -T backend ruff format --check .
133 files already formatted
### docker compose exec -T backend python manage.py check
System check identified no issues (0 silenced).
### docker compose exec -T backend python manage.py makemigrations --check --dry-run
No changes detected
### docker compose exec -T backend python manage.py test --noinput
2026-11-17 02:48:58,035 ERROR apps.agent.services.llm llm step=parse hata=RateLimitError status=429
2026-11-17 02:48:58,035 ERROR apps.agent.services.llm llm step=parse hata=AuthenticationError status=401
2026-11-17 02:48:58,035 ERROR apps.agent.services.llm llm step=parse hata=InternalServerError status=500
2026-11-17 02:48:58,036 WARNING apps.agent.services.llm llm step=parse max_tokens sınırına takıldı
2026-11-17 02:48:58,036 WARNING apps.agent.services.llm llm step=parse model reddetti
.2026-11-17 02:48:58,039 ERROR apps.agent.services.llm llm step=parse çıktı ayrıştırılamadı: ValueError
..........................................................................................................
----------------------------------------------------------------------
Ran 377 tests in 70.646s
OK
Destroying test database for alias 'default'...
### docker compose exec -T backend python manage.py build_search_index
İndeks kuruldu: 93310 film, süreler (sn): {'a': 22.3, 'b': 19.7, 'toplam': 42.2}, yol: /index/lexical
ACCEPTDONE
```

## Değerlendirme koşuları, kesin arama (exact)
```
### --set known50 --doc A,B,B_end --blend 0,0.3,0.5
known50 (kip exact, filtre yok)
| kol | grup | n | R@1 | R@10 | R@50 |
|---|---|---|---|---|---|
| RRF sırası | hepsi | 50 | %64 | %90 | %94 |
| RRF sırası | bilinen | 22 | %82 | %95 | %95 |
| RRF sırası | az bilinen | 28 | %50 | %86 | %93 |
| belge A, harman 0 | hepsi | 50 | %74 | %92 | %94 |
| belge A, harman 0 | bilinen | 22 | %64 | %95 | %95 |
| belge A, harman 0 | az bilinen | 28 | %82 | %89 | %93 |
| belge A, harman 0.3 | hepsi | 50 | %78 | %92 | %94 |
| belge A, harman 0.3 | bilinen | 22 | %77 | %95 | %95 |
| belge A, harman 0.3 | az bilinen | 28 | %79 | %89 | %93 |
| belge A, harman 0.5 | hepsi | 50 | %80 | %90 | %94 |
| belge A, harman 0.5 | bilinen | 22 | %82 | %95 | %95 |
| belge A, harman 0.5 | az bilinen | 28 | %79 | %86 | %93 |
| belge B, harman 0 | hepsi | 50 | %78 | %94 | %94 |
| belge B, harman 0 | bilinen | 22 | %68 | %95 | %95 |
| belge B, harman 0 | az bilinen | 28 | %86 | %93 | %93 |
| belge B, harman 0.3 | hepsi | 50 | %78 | %94 | %94 |
| belge B, harman 0.3 | bilinen | 22 | %77 | %95 | %95 |
| belge B, harman 0.3 | az bilinen | 28 | %79 | %93 | %93 |
| belge B, harman 0.5 | hepsi | 50 | %74 | %94 | %94 |
| belge B, harman 0.5 | bilinen | 22 | %77 | %95 | %95 |
| belge B, harman 0.5 | az bilinen | 28 | %71 | %93 | %93 |
| belge B_end, harman 0 | hepsi | 50 | %60 | %86 | %94 |
| belge B_end, harman 0 | bilinen | 22 | %45 | %86 | %95 |
| belge B_end, harman 0 | az bilinen | 28 | %71 | %86 | %93 |
| belge B_end, harman 0.3 | hepsi | 50 | %68 | %92 | %94 |
| belge B_end, harman 0.3 | bilinen | 22 | %59 | %95 | %95 |
| belge B_end, harman 0.3 | az bilinen | 28 | %75 | %89 | %93 |
| belge B_end, harman 0.5 | hepsi | 50 | %72 | %90 | %94 |
| belge B_end, harman 0.5 | bilinen | 22 | %68 | %95 | %95 |
| belge B_end, harman 0.5 | az bilinen | 28 | %75 | %86 | %93 |
Aday toplama (kip exact): ortanca 0.865 sn, en uzun 87.549 sn; toplam koşu 416.3 sn
JSON: /index/eval/known50-A+B+B_end-exact-20261117-012624.json
### --set tone25 --pool genome --doc A,B,B_end --blend 0,0.3,0.5
tone25 (kip exact, havuz genome, n=25)
| kol | P@10 | nDCG@10 | ortRel@10 | R@50 |
|---|---|---|---|---|
| RRF sırası | 0.312 | 0.562 | 0.534 | 0.199 |
| belge A, harman 0 | 0.216 | 0.501 | 0.491 | 0.199 |
| belge A, harman 0.3 | 0.264 | 0.503 | 0.501 | 0.199 |
| belge A, harman 0.5 | 0.284 | 0.531 | 0.515 | 0.199 |
| belge B, harman 0 | 0.352 | 0.635 | 0.607 | 0.199 |
| belge B, harman 0.3 | 0.376 | 0.636 | 0.607 | 0.199 |
| belge B, harman 0.5 | 0.364 | 0.627 | 0.600 | 0.199 |
| belge B_end, harman 0 | 0.260 | 0.564 | 0.545 | 0.199 |
| belge B_end, harman 0.3 | 0.288 | 0.557 | 0.555 | 0.199 |
| belge B_end, harman 0.5 | 0.288 | 0.563 | 0.544 | 0.199 |
Aday toplama (kip exact): ortanca 0.731 sn, en uzun 43.309 sn; toplam koşu 310.6 sn
JSON: /index/eval/tone25-A+B+B_end-exact-20261117-013141.json
### --set tone25 --pool genome --doc A
tone25 (kip exact, havuz genome, n=25)
| kol | P@10 | nDCG@10 | ortRel@10 | R@50 |
|---|---|---|---|---|
| RRF sırası | 0.312 | 0.562 | 0.534 | 0.199 |
| belge A, harman 0 | 0.216 | 0.501 | 0.491 | 0.199 |
Aday toplama (kip exact): ortanca 0.612 sn, en uzun 66.992 sn; toplam koşu 234.3 sn
JSON: /index/eval/tone25-A-exact-20261117-013554.json
### --set tone25 --pool genome --doc B
tone25 (kip exact, havuz genome, n=25)
| kol | P@10 | nDCG@10 | ortRel@10 | R@50 |
|---|---|---|---|---|
| RRF sırası | 0.312 | 0.562 | 0.534 | 0.199 |
| belge B, harman 0 | 0.352 | 0.635 | 0.607 | 0.199 |
Aday toplama (kip exact): ortanca 0.618 sn, en uzun 63.616 sn; toplam koşu 212.8 sn
JSON: /index/eval/tone25-B-exact-20261117-013937.json
### --set known50 --doc B
known50 (kip exact, filtre yok)
| kol | grup | n | R@1 | R@10 | R@50 |
|---|---|---|---|---|---|
| RRF sırası | hepsi | 50 | %64 | %90 | %94 |
| RRF sırası | bilinen | 22 | %82 | %95 | %95 |
| RRF sırası | az bilinen | 28 | %50 | %86 | %93 |
| belge B, harman 0 | hepsi | 50 | %78 | %94 | %94 |
| belge B, harman 0 | bilinen | 22 | %68 | %95 | %95 |
| belge B, harman 0 | az bilinen | 28 | %86 | %93 | %93 |
Aday toplama (kip exact): ortanca 0.842 sn, en uzun 270.609 sn; toplam koşu 524.1 sn
JSON: /index/eval/known50-B-exact-20261117-014832.json
### --set known50 --doc A,B --vector hnsw
### --set tone25 --pool genome --doc A,B --vector hnsw
ALLDONE
```

## Değerlendirme koşuları, HNSW
```
### --set known50 --doc A,B --vector hnsw
known50 (kip hnsw, filtre yok)
| kol | grup | n | R@1 | R@10 | R@50 |
|---|---|---|---|---|---|
| RRF sırası | hepsi | 50 | %64 | %90 | %94 |
| RRF sırası | bilinen | 22 | %82 | %95 | %95 |
| RRF sırası | az bilinen | 28 | %50 | %86 | %93 |
| belge A, harman 0 | hepsi | 50 | %76 | %92 | %94 |
| belge A, harman 0 | bilinen | 22 | %68 | %95 | %95 |
| belge A, harman 0 | az bilinen | 28 | %82 | %89 | %93 |
| belge B, harman 0 | hepsi | 50 | %78 | %94 | %94 |
| belge B, harman 0 | bilinen | 22 | %68 | %95 | %95 |
| belge B, harman 0 | az bilinen | 28 | %86 | %93 | %93 |
Aday toplama (kip hnsw): ortanca 6.201 sn, en uzun 369.975 sn; toplam koşu 1452.7 sn
JSON: /index/eval/known50-A+B-hnsw-20261117-023546.json
### --set tone25 --pool genome --doc A,B --vector hnsw
tone25 (kip hnsw, havuz genome, n=25)
| kol | P@10 | nDCG@10 | ortRel@10 | R@50 |
|---|---|---|---|---|
| RRF sırası | 0.312 | 0.562 | 0.534 | 0.199 |
| belge A, harman 0 | 0.216 | 0.501 | 0.491 | 0.199 |
| belge B, harman 0 | 0.352 | 0.635 | 0.607 | 0.199 |
Aday toplama (kip hnsw): ortanca 0.472 sn, en uzun 49.044 sn; toplam koşu 220.2 sn
JSON: /index/eval/tone25-A+B-hnsw-20261117-023931.json
ALLDONE
```

## 8 sorguda kesin / HNSW karşılaştırması (aynı süreç)
```
exact 0 188.52
exact 1 1.23
exact 2 1.03
exact 3 0.92
exact 4 1.06
exact 5 0.98
exact 6 0.92
exact 7 0.95
hnsw tur 1 0 241.26 ilk50 kesisim 49 hedef sira exact/hnsw 1 1
hnsw tur 1 1 94.34 ilk50 kesisim 48 hedef sira exact/hnsw 1 1
hnsw tur 1 2 96.18 ilk50 kesisim 49 hedef sira exact/hnsw 1 1
hnsw tur 1 3 32.01 ilk50 kesisim 50 hedef sira exact/hnsw 1 1
hnsw tur 1 4 18.11 ilk50 kesisim 47 hedef sira exact/hnsw 1 1
hnsw tur 1 5 6.33 ilk50 kesisim 47 hedef sira exact/hnsw 1 1
hnsw tur 1 6 4.78 ilk50 kesisim 41 hedef sira exact/hnsw 1 1
hnsw tur 1 7 4.36 ilk50 kesisim 50 hedef sira exact/hnsw 1 1
HNSW tur 1: ortanca 25.06 sn, en uzun 241.26 sn; ilk 50 kesisimi ortalama 47.6/50
hnsw tur 2 0 0.41 ilk50 kesisim 49 hedef sira exact/hnsw 1 1
hnsw tur 2 1 0.41 ilk50 kesisim 48 hedef sira exact/hnsw 1 1
hnsw tur 2 2 0.38 ilk50 kesisim 49 hedef sira exact/hnsw 1 1
hnsw tur 2 3 0.37 ilk50 kesisim 50 hedef sira exact/hnsw 1 1
hnsw tur 2 4 0.41 ilk50 kesisim 47 hedef sira exact/hnsw 1 1
hnsw tur 2 5 0.38 ilk50 kesisim 47 hedef sira exact/hnsw 1 1
hnsw tur 2 6 0.43 ilk50 kesisim 41 hedef sira exact/hnsw 1 1
hnsw tur 2 7 0.37 ilk50 kesisim 50 hedef sira exact/hnsw 1 1
HNSW tur 2: ortanca 0.39 sn, en uzun 0.43 sn; ilk 50 kesisimi ortalama 47.6/50
EXACT: ortanca 1.00 sn, en uzun 188.52 sn
```

## Soğuk açılış
```
COLD indeks yukleme sn 3.1
COLD gomme modeli sn 41.3
COLD yeniden siralama modeli sn 64.5
GPU bellek (bu surec, MiB) ayrilan/ayrilmis 2166 2678
```

## Bağdaştırıcı denemesi (apps.agent.services.retrieval.SearchServiceRetrieval, gerçek search, dil modeli yok)
```
14 objects imported automatically (use -v 2 for details).
limit=100 sure 122.15 aday 100 havuz 1991 gevsetilen ()
timings {'scope': 2.6209, 'index': 0.9705, 'encode': 38.7402, 'dense': 6.4655, 'hyde': 1.3725, 'card': 3.0059, 'bm25': 0.0372, 'g': 0.0004, 'fuse': 1.1441, 'gather': 54.3577, 'rerank': 67.2976, 'total': 121.684}
  48772 Come Undone 0.782 4 ('dense', 'bma', 'hyde', 'card', 'bmb')
  54079 The Returned 0.749 1 ('dense', 'bma', 'hyde', 'card', 'bmb')
  83191 Return to Bollene 0.749 31 ('dense', 'bma', 'hyde', 'card', 'bmb')
  52965 Strange Gardens 0.736 26 ('dense', 'bma', 'hyde', 'bmb')
  48749 Adventures of Félix 0.725 5 ('dense', 'bma', 'hyde', 'card', 'bmb')
rrf_rank tipi int sources tipi tuple
limit=20 exclude 1-100 sure 4.18 aday 20 havuz 1991 gevsetilen ()
timings {'scope': 0.9426, 'index': 0.0, 'encode': 0.0216, 'dense': 2.337, 'hyde': 0.0903, 'card': 0.1113, 'bm25': 0.0028, 'g': 0.0001, 'fuse': 0.0631, 'gather': 3.5692, 'rerank': 0.6098, 'total': 4.1795}
  48772 Come Undone 0.782 4 ('dense', 'bma', 'hyde', 'card', 'bmb')
  54079 The Returned 0.749 1 ('dense', 'bma', 'hyde', 'card', 'bmb')
  48749 Adventures of Félix 0.725 5 ('dense', 'bma', 'hyde', 'card', 'bmb')
  90579 Out of Season 0.679 15 ('dense', 'bma', 'hyde', 'card', 'bmb')
  51242 Man on the Train 0.662 11 ('dense', 'bma', 'card', 'bmb')
rrf_rank tipi int sources tipi tuple
imkansiz filtre -> gevsetilen ('year_max',) aday 10
DONE
```
