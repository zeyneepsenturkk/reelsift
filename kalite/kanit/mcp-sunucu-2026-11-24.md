# MCP sunucusu, gerçek istemciyle deneme (2026-11-24)

Ortam: backend `uvicorn config.asgi:application --lifespan on`, `mcp==2.3.0`, arama ısınması açık, RTX 4060. İstemci: resmî MCP Python SDK'sının istemcisi (streamable HTTP), adres `http://localhost:8000/mcp`. Makine deneme sırasında başka işlerle yüklüydü; süreler bu yüzden üst sınıra yakındır.

## Sonuçlar

- `initialize` 0,03 sn; `tools/list` -> `['film_ara', 'film_getir']` (0,04 sn).
- Arama modelleri ısınmadan `film_ara`: araç çökmedi, hata olarak döndü (0,01 sn).
- `film_ara`, adı verilmeden "Inception" tarifi (İngilizce, `adet=10`, ilk çağrı): 31,3 sn (modeller soğuk). Hedef film **1. sırada**. Sonraki sıralar: Henry's Crime, Lucid Dream, Ink, Dreams That Money Can Buy.
- `film_ara`, adı verilmeden "The Godfather" tarifi (`yil_en_az=1960`, `yil_en_cok=1980`, `ulke="United States of America"`, `adet=10`): 2,4 sn. Hedef film **4. sırada**; 2. sırada The Godfather Part II. Filtreler uygulandı.
- `film_getir(64897)` (Inception): 0,05 sn; ad, özgün ad, Türkçe ad, yıl, süre, ülke, tür, yönetmen, oyuncular, özet, hikâye metninden bölüm ve kaynak bağlantıları döndü.
- `film_getir(999999999)`: 0,02 sn, hata olarak döndü (film arşivde yok).

Tarifler `kalite/ham/` altındaki bilinen film tariflerinden alındı.
