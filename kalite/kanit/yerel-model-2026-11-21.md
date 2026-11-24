# Ozet: qwen3:4b-instruct-2507-q4_K_M vs Haiku (claude-haiku-5-5), 2026-11-21
Ollama 0.40.16 varsayilan ayar (flash attention/KV q8 degistirilmedi), temperature 0, num_ctx 12288, format = pydantic semasi (+istemde sema). Girdiler faz_a.json (Haiku parse + gercek arama, ilk 20 aday, ilk 4 fit film). Tek deneme/adim (temp 0 oldugu icin yeniden deneme ayni sonucu verir).

| adim | qwen sn (min-maks) | Haiku sn | JSON gecme (ilk deneme) | kalite notu |
|---|---|---|---|---|
| parse (4: 3 yeni + 1 refine) | 4.4-6.8 (ilk 28.1: yuk 22 sn) | 2.5-3.4 | 4/4 | intent 4/4 ayni; filtreler ayni; c1/c3 en_query biraz kaymis; uydurma film basligi (titles) 2/3 yeni istekte, Haiku bos birakti; refine: keep_draft farkli, yil 1950-69 + film noir (Haiku <=1989) |
| judge (20 film) | 9.4-17.0 | 8.7-11.7 | 3/3, kapsam 20/20 | Haiku ile verdict uyumu 11/20, 14/20, 10/20; Haiku daha siki (fit 2/13/5, Qwen 6/11/9); reason hepsi Turkce ama kisa/jenerik, bazilari sadece "fit" |
| select | 4.6-5.2 | 2.2-5.9 | 3/3 | basliklar Turkce; suggestions Haiku'dan zayif (istek degil anahtar kelime) |
| write (4 film) | 11.8-13.3 | 15.9-19.0 | 3/3, kapsam 4/4 | source_quote birebir 11/12 (Haiku 12/12); Turkce akici ama hatali ("shoemaker", "satir", "kaynakiyla"), 3 cumleyi asiyor/bicim kurali yer yer atlaniyor |

VRAM (backend acik, arama modelleri yuklu): bos 3299 MiB -> model yukluyken 7774 MiB (en yuksek); `ollama ps` 4.5 GB, %100 GPU, ctx 12288 (4282 MiB). Bos kalan ~400 MiB. Hicbir istemde 12288 asilmadi (en uzun judge 9335 token; Haiku sayimi 12.7k).
/api/health model yukluyken 200 ok. Gercek arama istegi atilamadi (acik arama ucu yok, sohbet ucu oturum ister): dogrulanmadi.
Haiku: 13 cagri, 81.756 girdi + 21.007 cikti token (tahmini <= ~0.2 dolar).
