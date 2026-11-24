# Faz 3 düzeltme turu ham çıktı

## Scope süresi öncesi / sonrası (sıcak, ortanca, timings['scope'])
```
ONCE  OLCUM A filtre (yil>=1990, Fransa) scope sn ortanca 0.085 bm25 sn 0.0026 g sn 0.0002 gather sn 0.296 havuz 2058 relaxed () ilk3 [48738, 54079, 63194]
ONCE  OLCUM B yalniz exclude (100 id) scope sn ortanca 0.092 bm25 sn 0.0209 g sn 0.0023 gather sn 0.972 havuz 3247 relaxed () ilk3 [14485, 65636, 35012]
ONCE  OLCUM C filtre (oy<=500) + exclude scope sn ortanca 0.1968 bm25 sn 0.0204 g sn 0.0023 gather sn 1.791 havuz 3191 relaxed () ilk3 [14485, 65636, 35012]
SONRA OLCUM A filtre (yil>=1990, Fransa) scope sn ortanca 0.1214 bm25 sn 0.0027 g sn 0.0 gather sn 0.332 havuz 2058 relaxed () ilk3 [48738, 54079, 63194]
SONRA OLCUM B yalniz exclude (100 id) scope sn ortanca 0.0001 bm25 sn 0.0197 g sn 0.0 gather sn 0.849 havuz 3247 relaxed () ilk3 [14485, 65636, 35012]
SONRA OLCUM C filtre (oy<=500) + exclude scope sn ortanca 0.1677 bm25 sn 0.0183 g sn 0.0 gather sn 1.775 havuz 3191 relaxed () ilk3 [14485, 65636, 35012]
```
## Isındırma (compose up -d backend)
```
backend-1  | 2026-11-17 03:06:15,754 INFO apps.agent.runtime Agent grafı hazır
backend-1  | 2026-11-17 03:06:16,859 INFO apps.search.services.warmup Arama ısındırma: index 0.8 sn
backend-1  | 2026-11-17 03:07:07,730 INFO apps.search.services.warmup Arama ısındırma: embed_model 50.9 sn
backend-1  | 2026-11-17 03:08:21,787 INFO apps.search.services.warmup Arama ısındırma: rerank_model 74.1 sn
backend-1  | 2026-11-17 03:09:49,040 INFO apps.search.services.warmup Arama ısındırma: dummy_search 87.3 sn
backend-1  | 2026-11-17 03:09:49,040 INFO apps.search.services.warmup Arama hazır (213.0 sn)
backend-1  | 2026-11-17 03:48:07,448 INFO apps.agent.runtime Agent grafı hazır
backend-1  | 2026-11-17 03:48:30,935 INFO apps.search.services.warmup Arama ısındırma: index 23.3 sn
health: ısınma sürerken 200 (0,9-1,7 sn; açılış sırasında ilk 3 deneme bağlantı yok)
WARM adimlar {'index': 6.0, 'embed_model': 37.2, 'rerank_model': 65.5, 'dummy_search': 59.9} toplam 168.7
ILK SEARCH (ayni surecte warm sonrasi) 1 sn 10.16 aday 50
ILK SEARCH (ayni surecte warm sonrasi) 2 sn 2.07 aday 50
```
## Kabul + değerlendirme
```
### docker compose exec -T backend ruff check .
All checks passed!
### docker compose exec -T backend ruff format --check .
136 files already formatted
### docker compose exec -T backend python manage.py check
System check identified no issues (0 silenced).
### docker compose exec -T backend python manage.py makemigrations --check --dry-run
No changes detected
### docker compose exec -T backend python manage.py test --noinput
----------------------------------------------------------------------
Ran 389 tests in 54.485s
FAILED (failures=1)
Destroying test database for alias 'default'...
### docker compose exec -T backend python manage.py evaluate_search --set known50 --doc B
known50 (kip exact, filtre yok)
| kol | grup | n | R@1 | R@10 | R@50 |
|---|---|---|---|---|---|
| RRF sırası | hepsi | 50 | %64 | %90 | %94 |
| RRF sırası | bilinen | 22 | %82 | %95 | %95 |
| RRF sırası | az bilinen | 28 | %50 | %86 | %93 |
| belge B, harman 0 | hepsi | 50 | %78 | %94 | %94 |
| belge B, harman 0 | bilinen | 22 | %68 | %95 | %95 |
| belge B, harman 0 | az bilinen | 28 | %86 | %93 | %93 |
Aday toplama (kip exact): ortanca 0.956 sn, en uzun 54.206 sn; toplam koşu 475.8 sn
JSON: /index/eval/known50-B-exact-20261117-033850.json
### docker compose exec -T backend python manage.py evaluate_search --set tone25 --pool genome --doc B
tone25 (kip exact, havuz genome, n=25)
| kol | P@10 | nDCG@10 | ortRel@10 | R@50 |
|---|---|---|---|---|
| RRF sırası | 0.312 | 0.562 | 0.534 | 0.199 |
| belge B, harman 0 | 0.352 | 0.635 | 0.607 | 0.199 |
Aday toplama (kip exact): ortanca 0.736 sn, en uzun 85.068 sn; toplam koşu 280.6 sn
JSON: /index/eval/tone25-B-exact-20261117-034353.json
ACCEPTDONE
(test: düzeltme sonrası 389 test OK)
```
