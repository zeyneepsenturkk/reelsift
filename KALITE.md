# KALİTE GÜNLÜĞÜ

Arama ve öneri kalitesini nasıl ölçtüğümüz ve her adımın kaliteyi ne kadar değiştirdiği burada tutulur. Sunumda "kaliteyi nasıl artırdınız?" sorusunun kaynağıdır. Ekleme-only: eski ölçüm silinmez, yenisi alta eklenir. Ham çıktılar `kalite/ham/` altındadır.

## Ölçüm yöntemleri

| Test | Nasıl yapılır | Ne ölçer |
|---|---|---|
| Bilinen film testi | Arşivdeki bir film, adı ve özel isimler kullanılmadan tek cümleyle tarif edilir; sistem o filmi 92 bin film içinde kaçıncı sırada buluyor diye bakılır | İlk 1 / ilk 10 / ilk 50'de bulma oranı (R@1, R@10, R@50) ve ortanca sıra |
| Tema testi | Sabit tematik istekler için ilk 10 sonuç okunur; her sonuç uygun / kısmen / alakasız diye işaretlenir | İstek başına uygun sonuç oranı |
| Pratiklik | Süre ve bellek ölçülür | Sorgu çevirme süresi, arama süresi, disk ve bellek |

Sınırlar: tarifleri ve uygunluk yargılarını şimdilik yapay zekâ ajanı yazıyor; örneklem küçük. Sonuçlar yön gösterir, kesin hüküm değildir.

## Özet tablo (bilinen film testi)

| tarih | adım | sorgu dili | R@1 | R@10 | R@50 | ortanca sıra | tarif sayısı |
|---|---|---|---|---|---|---|---|
| 2026-11-13 | Taban: film başına tek hazır vektör (bge-m3), düz arama | Türkçe | %12 | %28 | %36 | 117 | 25 |
| 2026-11-13 | Taban, sorgu İngilizce | İngilizce | %24 | %40 | %56 | 30 | 25 |
| 2026-11-13 | (2. tur) Taban: tek hazır vektör, düz arama | Türkçe | %8 | %16 | %26 | 347 | 50 |
| 2026-11-13 | (2. tur) Taban, sorgu İngilizce | İngilizce | %14 | %26 | %40 | 169 | 50 |
| 2026-11-13 | (2. tur) Chunk'lı indeks (en iyi parça skoru) | Türkçe | %8 | %22 | %42 | 85 | 50 |
| 2026-11-13 | (2. tur) Chunk'lı indeks | İngilizce | %16 | %36 | %58 | 34 | 50 |
| 2026-11-13 | (2. tur) Chunk'lı indeks + ilk 50 adaya yeniden sıralama (bge-reranker-v2-m3, tam hikâye üzerinden) | İngilizce | %46 | %58 | %58 | 2 | 50 |
| 2026-11-13 | (3. tur) Önekli chunk (başlık + tür + ülke), tam arşiv | İngilizce | %34 | %52 | %64 | 8 | 50 |
| 2026-11-13 | (3. tur) Yalnız kelime araması (BM25) | İngilizce | %52 | %80 | %84 | 1 | 50 |
| 2026-11-13 | (3. tur) Birleşik hat: önekli chunk + kelime araması + çoklu sorgu + hayali hikâye + modelin önerdiği adlar | İngilizce | %54 | %92 | %94 | 1 | 50 |
| 2026-11-13 | (3. tur) Birleşik hat + ilk 50 adaya yeniden sıralama | İngilizce | %68 | %88 | %94 | 1 | 50 |
| 2026-11-13 | (4. tur) Gerçek model (Gemini) Türkçe istekten arama cümlesi + hayali hikâye + film adı yazıyor; TMDB'siz hat + yeniden sıralama (hikâye) | Türkçe girdi | %66 | %82 | %90 | – | 50 |
| 2026-11-13 | (4. tur) Yukarıdaki + TMDB film kartı vektörü + TMDB metinli kelime araması + kısa hikâye eleme + yeniden sıralamaya TMDB tanıtım yazısı | Türkçe girdi | %72 | %88 | %94 | – | 50 |
| 2026-11-17 | (faz 3, uygulama içi) Haiku çözümlemeleri (kayıtlı), tam hat, yeniden sıralama belge A (TMDB özeti + hikâye) | Türkçe girdi | %74 | %92 | %94 | – | 50 |
| 2026-11-17 | (faz 3, uygulama içi) Aynısı, yeniden sıralama belge B (film profili + A); uygulamanın varsayılanı | Türkçe girdi | %78 | %94 | %94 | – | 50 |
| 2026-11-17 | (kişi araması ve Türk filmleri sonrası) Aynı hat, belge B; arşiv 94.683 film (1.373 Türk filmi eklendi), kişi dizini ve genişlemiş ad indeksiyle | Türkçe girdi | %78 | %94 | %94 | – | 50 |

Not: 3. tur sayıları iyimserdir (bkz. 3. tur kaydındaki uyarılar): tarifler hedef hikâyeden türetildiği için kelime araması avantajlı; sorgu zenginleştirme metinlerini gerçek sohbet modeli değil ölçümü yapan ajan yazdı.

Not: 50 tariflik set 25'liğe göre daha zor (bilinen + kısa hikâyeli ve az bilinen + uzun hikâyeli filmler eklendi); bu yüzden taban sayıları 1. turdan düşük. Adımlar arası karşılaştırma aynı set içinde yapılır.

## Ölçümler

### 2026-11-13, 1. tur: taban ölçümü
- Kurulum: Hugging Face `NiklasAbraham/MoviePlotEmbeddingsDataset` hazır vektörleri (92.374 film, 1024 boyut, bge-m3), sorgu yerelde bge-m3 ile vektöre çevrildi, düz en yakın komşu araması.
- Uyum: 30 filmde kendi ürettiğimiz vektör ile hazır vektörün benzerliği ortalama 1,00; 30/30 doğru film ilk sırada. Hazır vektörler doğrudan kullanılabilir.
- Bilinen film testi: yukarıdaki tablo. Az bilinen filmlerde (oy sayısı < 500) Türkçe R@10 %58; çok bilinen filmlerde ilk 50'de hiçbiri yok.
- Tema testi (8 Türkçe istek, ilk 10, uygun/kısmen/alakasız): savaş sonrası travma 6/2/2; çocukluk arkadaşlarının buluşması 7/3/0; soygun komedisi 5/3/2; kasaba, yas, dram 2/8/0; yapay zekâ bilim kurgu 2/2/6; mahsur kalan grup 2/4/4; kimlik sorgulayan psikolojik gerilim 1/5/4; kuzey ülkesi polisiyesi 0/2/8. (Yargılar hikâyenin ilk 150 karakterine bakılarak verildi.)
- Pratiklik: model 2,32 GB; tek sorgu ekran kartıyla 17 ms, işlemciyle 98 ms; 92 bin vektörde arama 10 ms.
- Tespit edilen sorunlar:
  1. Türkçe sorguda çapraz dil kaybı (R@10 %28, İngilizcede %40).
  2. Kısa sorgu uzun hikâyelerle zayıf eşleşiyor; çok kısa hikâyeli filmler öne geçiyor (hikâye uzunluğu ile sıra arasında korelasyon 0,75).
  3. Atmosfer ve coğrafya hikâye metninde yazmıyor ("kuzey ülkesi polisiyesi" hiç Kuzey Avrupa filmi getirmedi).
  4. Sonuçlar çok kısa hikâyeli, çok az oylu filmlerle doluyor.
- Planlanan çözümler: sorguyu İngilizce yazdırma; uzun hikâyeleri parçalara bölme (chunking); ülke ve tür için yapısal filtre; yeniden sıralama (reranking).
- Ham çıktı: `kalite/ham/2026-11-13-tur1-sonuc.md`, tarifler: `kalite/ham/2026-11-13-tur1-tarifler.json`.

### 2026-11-13, 2. tur: iyileştirme adımlarının ölçümü
- Test seti: 50 tarif (1. turun 25'i + 25 yeni: 9 bilinen + kısa hikâyeli, 16 az bilinen + uzun hikâyeli). Tarifler sonuç görülmeden yazıldı, sonradan değiştirilmedi. "Bilinen" = oy sayısı 1000 ve üstü; "uzun hikâye" = 3000 karakter ve üstü.
- Chunk'lı indeks: 92.374 filmin tamamı; hikâyeler cümle sınırına saygılı ~150-200 kelimelik, ~30 kelime örtüşmeli parçalara bölündü; 217.073 parça (ortalama 154 kelime), bge-m3 ile RTX 4060'ta 25 dakikada vektöre çevrildi (61 film/sn). Film skoru = en iyi parçanın skoru.
- Adım adım kazanç (R@10): taban Türkçe %16 -> sorgu İngilizce %26 -> chunk %36 -> yeniden sıralama %58. İlk sırada bulma (R@1) %8'den %46'ya, ortanca sıra 347'den 2'ye.
- Chunking uzun hikâyeleri kurtardı: uzun hikâyeli filmlerde R@50 tek vektörle %3, chunk ile %31 (Türkçe) / %48 (İngilizce).
- Parçanın başına başlık + tür + ülke eklemek (20.050 filmlik alt kümede ölçüldü, tam arşivde değil): İngilizce sorguda R@10 %52 -> %64, R@1 %28 -> %40. Tam arşivde yeniden ölçülecek.
- Yeniden sıralama yalnız ilk 50 adayı sıralıyor; ilk 50'ye giremeyen filmi kurtaramıyor (R@50 tavanı %58).
- Basit skor birleştirme (tek vektör + chunk, 0,5/0,5) işe yaramadı (R@10 %32).
- Ülke filtresi ("kuzey ülkesi polisiyesi"): filtresiz ilk 10'da uygun film 0; İskandinav ülkesi + suç/gerilim türü filtresinden sonra 6 uygun / 4 kısmen (Türkçe sorgu). Ülke sütunu %99,1 dolu.
- Tema testi (8 istek x ilk 10 = 80 sonuç; uygun/kısmen/alakasız, hikâyeler tam okunarak): taban 29/30/21, chunk Türkçe 30/30/20, chunk İngilizce 33/30/17. En belirgin düzelme "yapay zekâ bilim kurgu" (3 uygun -> 5 uygun). Yargılar özneldir, küçük farklar gürültü sayılır.
- Süreler: yeniden sıralama 50 aday için ekran kartıyla 0,4-0,6 sn, işlemciyle 11-19 sn. Chunk vektörleri 445 MB.
- Hâlâ zayıf kalanlar:
  1. Çok bilinen filmler: chunk + İngilizce sorguda R@10 bilinenlerde %14, az bilinenlerde %54. Neden doğrulanmadı (tahmin: bazı ünlü filmlerin hikâye metni birkaç cümlelik, benzer rakip çok).
  2. Soyut temalar ("kimliğini sorgulayan kadın") ve ton/atmosfer; coğrafya yalnız filtreyle düzeliyor.
  3. Yeniden sıralama ekran kartsız yavaş.
- Planlanan sonraki denemeler: aday havuzunu 50'den büyütmek; anahtar kelime aramasıyla birleştirme; modelin kendi bildiği film adlarını önerip arşivde doğrulatması (bilinen filmler için); popülerliği sıralamada ikincil sinyal olarak kullanmak; önekli chunk'ı tam arşivde ölçmek.
- Ham çıktı: `kalite/ham/2026-11-13-tur2-sonuc.md`; yeni tarifler: `kalite/ham/2026-11-13-tur2-tarifler-yeni25.json`; betikler: `kalite/ham/2026-11-13-tur2-*.py`.

### 2026-11-13, 3. tur: aday havuzunu büyütme yöntemleri
- Amaç: 2. turun darboğazını çözmek (doğru film vakaların %42'sinde ilk 50 adaya giremiyordu).
- Aynı 50 tarif, 92 bin film. Sorgu zenginleştirme metinleri (çoklu sorgu, hayali hikâye, önerilen film adları) hedef film adı görülmeden, yalnız tarif cümlelerinden yazıldı ve sonradan değiştirilmedi.
- Teşhis (ilk 50'ye giremeyen 21 hedef, 15'i bilinen film): hepsinde üst sıraları 1-2 cümlelik hikâyesi olan çok az bilinen filmler kaplıyor (ilk 5 rakibin 101/105'i oy sayısı 130 ve altı). Sorun parça seçimi değil, kısa hikâyeli filmlerin kısa sorguya daha çok benzemesi. Ayrıca 5 bilinen filmin arşivdeki hikâye metni filmin özünü anlatmayan kısa bir metin (Into the Wild, City of God, Babel, Melancholia, Wild Tales).
- Yöntemler tek tek (R@10, hepsi / bilinen / az bilinen):
  - Chunk (2. tur): %36 / %14 / %54
  - Önekli chunk: %52 / %32 / %68
  - Kelime araması (BM25): %80 / %68 / %89
  - Hayali hikâye (HyDE): %60 / %82 / %43
  - Çoklu sorgu (3 cümle): %42 / %41 / %43
  - Modelin önerdiği film adları (arşivde doğrulanarak): %64 / %100 / %36
- Birleşik hat: R@10 %92, R@50 %94; bilinen filmlerde R@10 %14'ten %100'e. Yeniden sıralamayla R@1 %68.
- Bileşen çıkarma (ablation): en çok katanlar kelime araması ve modelin önerdiği adlar, sonra hayali hikâye. Çoklu sorgu bu yazımla katkısız. Önek tek başına büyük kazanç, diğerleri varken ek kazancı yok.
- Yeniden sıralama havuzu: ilk 50 aday en iyi sonucu veriyor (R@1 %68, ~1,1 sn); 200 aday daha iyi değil (R@1 %64) ve ~4 sn sürüyor.
- Modelin önerdiği adlar: 250 önerinin 213'ü (%85) arşivde bulundu; 37'si arşivde yok (Pulp Fiction ve The Godfather Part II dahil: arşivde eksik filmler var). Hedef film önerilerde: bilinen 22/22, az bilinen 10/28.
- Tema testi (8 istek, 80 sonuç, uygun/kısmen/alakasız): 2. tur chunk 33/30/17 -> birleşik hat 37/35/8. Kazanç esas olarak alakasızların azalması. "Kuzey ülkesi polisiyesi" filtresiz hâlâ zayıf (1/5/4).
- Uyarılar (sonuçlar iyimser):
  1. Tarifler hedef filmin hikâyesinden türetildi; aynı kelimeleri paylaştığı için kelime araması gerçek editör isteğine göre avantajlı.
  2. Hayali hikâye ve film adı önerilerini ölçümü yapan ajan (bir dil modeli) yazdı ve bilinen filmleri tariften tanıdı; gerçek sistemdeki sohbet modeliyle yeniden ölçülmeli.
  3. Tek ölçüm, 50 tarif; 1 tarif = 2 puan.
- Hâlâ zayıf: soyut/tematik isteklerde kazanç sınırlı; 3 hedef ilk 200'de bile yok; arşivde bazı ünlü filmler eksik.
- Sonraki adım: TMDB tanıtım yazısı ve anahtar kelimeleriyle zenginleştirme (4. tur); zenginleştirme metinlerini gerçek sohbet modeline yazdırma; insan elinden çıkmış tematik isteklerle ölçüm; çok kısa hikâyeli filmler için alt sınır/ceza.
- Ham çıktı: `kalite/ham/2026-11-13-tur3-sonuc.md`, teşhis: `kalite/ham/2026-11-13-tur3-teshis.md`, üretilen sorgular: `kalite/ham/2026-11-13-tur3-uretilen-sorgular.json`.

### 2026-11-13, 4. tur: gerçek model, TMDB zenginleştirmesi, filtreler
- Fark: sorgu zenginleştirme metinlerini (İngilizce arama cümlesi, hayali hikâye, film adı önerileri, filtreler) bu kez gerçek bir sohbet modeli yazdı ve girdi Türkçe verildi. Model: Gemini (70 isteğin 24'ü gemini-3.5-flash, 46'sı kota dolduğu için gemini-3.1-flash-lite; karışık).
- TMDB verisi: 87.176 film çekildi (66 dk, hata yok). Doluluk: tanıtım yazısı %99, afiş %97, en az bir anahtar kelime %65 (film başına ortanca 2), Türkçe ad %20 (2015+ filmlerde %31), Türkçe özet %23.
- Bilinen film testi (50 tarif, Türkçe girdi; R@1 / R@10 / R@50):
  - Ajan yazımı metinlerle (3. tur referansı): %68 / %88 / %94
  - Gemini yazımı, TMDB'siz: %66 / %82 / %90
  - Gemini + TMDB kart vektörü + TMDB metinli kelime araması: %66 / %86 / %94
  - Yukarıdaki + kısa hikâye eleme + yeniden sıralamaya TMDB tanıtım yazısı: %72 / %88 / %94 (bilinen %59 / %91 / %100; az bilinen %82 / %86 / %89)
  - Sonuç: gerçek model ve Türkçe girdiyle sayılar ajan yazımıyla aynı düzeyde; 3. turdaki şişme büyük değilmiş.
- TMDB'nin katkısı: bilinen film testinde orta (R@50 %90 -> %94; yeniden sıralamaya tanıtım yazısı eklemek R@10 %82 -> %88). Tematik testte tek başına katkı yok.
- Kısa hikâye kuralı: hikâyesi 300 karakterden kısa olup model önerisiyle eşleşmeyen filmleri elemek, puan cezasından iyi; kazanç küçük (R@1 +2 puan), zararı yok.
- Tematik test (20 Türkçe istek x ilk 10 = 200 sonuç; uygun / kısmen / alakasız; yargılar özneldir, tek yargıç):
  - TMDB'siz hat: 61 / 57 / 82
  - TMDB'li hat: 58 / 54 / 88
  - TMDB'li hat + modelin çıkardığı filtreler (yıl, ülke, tür, oy sayısı): 75 / 66 / 59
  - Filtresiz hatlarda ilk 10'larda yıl kısıtı 30+, ülke kısıtı 8-13 kez ihlal edildi; filtreli hatta ihlal 0.
  - En çok kazanan istekler dönem/ülke içerenler (ör. "1960 öncesi siyah beyaz savaş karşıtı" 1 -> 4 uygun, "küçük Fransız kasabası aile komedisi" 1 -> 4). Saf ton/atmosfer isteklerinde fark yok.
- Filtre uyarısı: model çoğu istekte tür filtresi de koyuyor; bilinen film testinde filtre uygulanınca sonuç düştü (%64 / %80 / %86). Karar: yıl, ülke, oy sayısı sert filtre; tür yumuşak (tercih) olarak uygulanacak.
- Süreler: arama + birleştirme ~0,03 sn, yeniden sıralama (50 aday) ~1,1 sn. Darboğaz dil modeli çağrısı (Gemini ortalama 14 sn; 3.5-flash 30 sn, flash-lite 6 sn).
- Hâlâ zayıf: ton/atmosfer istekleri ("ayrılık sonrası umut veren", "soygun komedisi"); arşivde az temsil edilen alanlar ("90'lar Japon korku": filtreli hatta bile 3 uygun); az bilinen hedeflerde R@50 %89.
- Sınır: bu ölçümler aramanın getirdiği ilk 10'u ölçüyor. Üründe son listeyi adayların hikâyesini okuyan model seçecek; o adımın etkisi sistem kurulunca uçtan uca ölçülecek.
- Ham çıktı: `kalite/ham/2026-11-13-tur4-sonuc.md`, tablolar: `kalite/ham/2026-11-13-tur4-bilinen-film-tablolari.md`, model çıktıları: `kalite/ham/2026-11-13-tur4-gemini-ciktilari.json`, yargılar: `kalite/ham/2026-11-13-tur4-tematik-yargilar.txt`.

### 2026-11-13, 4. tur ek ölçüm: Claude Haiku 5.5 ile sorgu çözümleme
- Aynı 70 istek (50 tarif + 20 tematik), aynı istem, aynı arama hattı; sadece sorgu çözümlemeyi yapan model değişti (Gemini karışık -> Claude Haiku 5.5, effort low). 70/70 çağrı başarılı, JSON hatası 0.
- Bilinen film testi (R@1 / R@10 / R@50), Gemini -> Haiku:
  - Son hat (TMDB'li + kısa hikâye eleme + tanıtım yazılı yeniden sıralama): %72 / %88 / %94 -> %72 / %92 / %94
  - Filtreler uygulanmış hat: %64 / %80 / %86 -> %62 / %88 / %94 (Haiku'nun filtreleri hedef filmi daha az dışarıda bıraktı)
- Film adı önerileri: bilinen filmlerde ikisi de 22/22; az bilinen filmlerde Gemini 12/28, Haiku 3/28. Önerilen adların arşivde bulunma oranı Gemini 93/96, Haiku 90/100.
- Filtre kalitesi (20 tematik istek): yıl, ülke ve oy sayısı kararları iki modelde neredeyse aynı. İstekte geçmediği halde tür filtresi: Gemini 5 istek, Haiku 4 istek.
- Tematik test (200 sonuç, uygun / kısmen / alakasız): tüm filtrelerle Gemini 75 / 66 / 59, Haiku 76 / 71 / 53. Haiku'da tür filtresi kaldırılınca 68 / 72 / 60 (tür filtresi Haiku'da yardımcı oldu; Gemini'de bilinen film testinde zarar görülmüştü: karar "tür yumuşak tercih" olarak kalıyor, sistemde yeniden ölçülecek).
- Süre: Haiku ortalama 4,4 sn (en uzun 7,9); Gemini ortalama 14 sn (kota hataları ve yeniden denemeler dahil). Maliyet: Haiku istek başına ~0,0004 dolar (girdi 573, çıktı 738 token), 1000 istek ~0,43 dolar.
- Sonuç: Haiku 5.5 geliştirme modeli olarak yeterli; Gemini ile eşit ya da biraz iyi, daha hızlı ve kararlı. Zayıf yanı az bilinen filmleri adıyla önermek; o filmleri arama hattı (anlamsal + kelime) buluyor. Farklar 1-2 film düzeyinde, tek yargıç.
- Ham çıktı: `kalite/ham/2026-11-13-tur4b-haiku-sonuc.md`, model çıktıları: `kalite/ham/2026-11-13-tur4b-haiku-ciktilari.json`, istem: `kalite/ham/2026-11-13-tur4-sorgu-cozumleme-istemi.py`.

### 2026-11-13, arşivi tamamlama (veri kalitesi)
- Eksik bilinen filmler: TMDB'nin en çok oy alan 9.836 filminden 941'i arşivde yoktu (ilk 1000 içinde 23, ilk 5000 içinde 326). Örnekler: Deadpool, Pulp Fiction, Joker, The Godfather Part II, A Clockwork Orange, Moonlight. Hepsinin TMDB verisi çekildi; 695'inin hikâyesi Wikipedia'dan alındı (ortanca 3.524 karakter), 246'sında hikâye bölümü bulunamadı. Not: 5 film aslında başka kimlikle arşivde var, gerçek eksik ~930.
- Kısa hikâyeleri yenileme: 300 filmlik örnekte yalnız %6,3'ünde Wikipedia'daki güncel hikâye belirgin uzundu (oy sayısı 100 ve üstünde %11,3; altında %1,3). Bu yüzden yalnız bilinen filmler işlendi: 1.166 filmden 139'unun hikâyesi uzadı (ortanca 302 -> 3.913 karakter).
- İncelemeler (TMDB kullanıcı incelemeleri): en az bir incelemesi olan film oranı oy sayısına göre: 20 altı %6, 20-100 arası %17, 100-1000 arası %44, 1000 üstü %88. Oy sayısı 100 ve üstü 18.172 film tarandı; 9.843 film için 20.485 inceleme alındı (film başına en fazla 5, en uzunlar; ortanca ~1.000 karakter; yazar adı saklanmadı). Karar: incelemeler arama indeksine girmez, kanıt olarak kullanılır.
- Çıktılar: `D:\reelsift-data\arsiv-ek\` (`eksik_filmler.jsonl`, `plot_yenileme.jsonl`, `incelemeler.jsonl`); ham rapor `kalite/ham/2026-11-13-arsiv-tamamlama-rapor.md`. Bu veriler henüz vektöre çevrilmedi ve veritabanına yüklenmedi (faz 2'nin işi).

### 2026-11-13, 5. tur: film profili denemesi (6.000 filmlik alt küme)
- Fikir: Wikipedia hikâyesi olayları anlatır, editör ton/atmosfer/tema sorar. Her film için Claude Haiku 5.5'e hikâye + TMDB bilgisi okutulup kısa bir profil yazdırıldı (temalar, ton listesinden 2-4 değer, ton cümlesi, tempo, mekân/dönem, anlatım özellikleri, "kimler için", Türkçe tek cümle tanıtım, kanıt düzeyi). Kural: yalnız verilen metinden, dış bilgi yok.
- Alt küme: 50 bilinen-film hedefi + 90 sorgu listesinin üst sıraları (3.500 film) + 2.500 rastgele = 6.000 film. Taban hat da aynı alt kümede yeniden ölçüldü. Sorgu çözümleme: Haiku 5.5.
- Üretim: 6.000/6.000 başarılı; kanıt düzeyi zengin 4.721, zayıf 1.193, yetersiz 85. Film başına ortalama 1.441 girdi + 825 çıktı token; 6.000 film 3,34 dolar, 20 dakika (5,2 film/sn). 10 profil hikâyeyle karşılaştırıldı: uydurma olay/kişi 0; 3'ünde hafif dayanaksız ayrıntı (çoğu tempo tahmini). "tense" filmlerin yarısında çıktı (ayırt ediciliği zayıf); tempo alanı %79 "bilinmiyor".
- Bilinen film testi (50 tarif; R@1 / R@10 / R@50): taban %72 / %92 / %94; profil arama kaynağı olarak eklenince %72 / %92 / %96; profil yeniden sıralama girdisine de eklenince %80 / %94 / %96.
- Tematik test (20 istek x ilk 10 = 200 sonuç; uygun / kısmen / alakasız):
  - Taban (TMDB'li hat + yıl/ülke/oy sayısı filtresi): 67 / 75 / 58
  - + profil arama kaynağı olarak (anlamsal + kelime): 70 / 77 / 53
  - + profil yeniden sıralama girdisinde: 109 / 72 / 19
  - + ton eşleşmesine artı puan: 109 / 73 / 18 (fark yok)
  - Ton/atmosfer istekleri (5 istek): taban 11 / 20 / 19 -> profil yeniden sıralamada 22 / 20 / 8. Örnek: "kuzey ülkesi polisiyesi" 2 -> 6 uygun, "soygun komedisi" 0 -> 7 uygun.
- Sonuç: kazanç profilin yeniden sıralama modeline girdi olarak verilmesinden geliyor; arama kaynağı olarak etkisi yok denecek kadar az.
- Sınırlar: (1) yargılar öznel ve tek yargıç; eski çiftleri önceki turların yargıçları, yeni 121 çifti bu turun yargıcı değerlendirdi; profilli hattın sonuçları en çok yeni çift içerdiği için yargıç farkı sonucu şişirmiş olabilir; MovieLens ton anahtarıyla bağımsız doğrulama yapılacak. (2) 6.000 filmlik alt küme; 92 bin filmde rakip daha fazla. (3) Profil metni yeniden sıralama girdisinin başına eklendi; hikâyenin kesilme etkisi ayrı ölçülmedi.
- Hata kaydı: ilk üretim koşusunda girdi hazırlama hatası yüzünden hikâye metni yerine boş bir değer gitti; koşu (yaklaşık 3,2 dolar) atıldı ve düzeltilip yeniden üretildi. Atılan koşu "yalnız TMDB metninden profil" karşılaştırması olarak raporda duruyor (bilinen film testinde hikâyeli profille benzer; tematik yargısı yapılmadı).
- Çıktılar: `D:\reelsift-data\profil\deneme-6000\`; ham rapor `kalite/ham/2026-11-13-tur5-profil-sonuc.md`, istem `kalite/ham/2026-11-13-tur5-profil-istemi.txt`.

### 2026-11-13, profilin tüm arşive yazdırılması (toplu işlem gönderildi)
- Karar: deneme sonucu olumlu, kullanıcı onayladı. 93.314 filmden (92.374 arşiv + 940 eksik film) 6.000'i denemede hazır; kalan 87.314 film Claude Message Batches API ile 9 parti halinde 2026-11-13 21:43-21:45'te gönderildi (model `claude-haiku-5-5`, denemeyle aynı istem ve parametreler). Tahmini maliyet ~24 dolar (toplu işlem fiyatı). Sonuçlar gönderimden itibaren 29 gün saklanır.
- 139 filmde hikâye olarak yenilenmiş Wikipedia metni kullanıldı.
- Dosyalar: `D:\reelsift-data\profil\` (`batch_ids.json`, `istekler_*.jsonl`, `gonder.py`, `indir.py`, `OKUBENI.txt`). İndirme komutu: `D:\reelsift-data\profil\venv\Scripts\python.exe D:\reelsift-data\profil\indir.py`. `indir.py` gerçek API ile henüz denenmedi.
- Açık: profil kazancının MovieLens ton anahtarıyla bağımsız doğrulanması (yargıç farkı olasılığı nedeniyle).

### 2026-11-13, otomatik değerlendirme seti (hazırlandı, henüz ölçüm yapılmadı)
- Amaç: insan puanlaması olmadan, arama indeksinde bulunmayan bağımsız verilerle ölçüm.
- Konu anahtarı: Wikipedia "List of films ..." sayfalarından 30 konu listesi (zaman döngüsü, sınıf çatışması, hapishane, hayalet, savaş karşıtı, yapay zekâ, hazine avı, ev baskını ...). Liste başına arşivde bulunan film 38-678. Her konu için editör diliyle Türkçe istek cümlesi yazıldı. Sınırlar: sayfadaki bağlantılar "film mi" diye Wikidata'dan doğrulanamadı (API sınırı); giriş yazısında anılan film sızmış olabilir; liste üyeliği kısmen hikâye metnine dayandığı için orta düzey sızıntı riski var; listeler eksik olabildiğinden sonuç alt sınırdır.
- Ton anahtarı: MovieLens ml-25m Tag Genome (kullanım koşulu: araştırma amaçlı serbest, yeniden dağıtım ve ticari kullanım izinsiz yasak; yalnız yerelde, ölçüm için). Genome'daki 13.816 filmden 12.417'si arşivde. Kapsam bilinen filmlerde yüksek (oy sayısı 1000 üstünde ~%83), az bilinenlerde çok düşük (50 altında ~%1,5); veri 2019'da bitiyor (2015+ filmlerden 1.239'u). 43 ton etiketi seçildi (bleak 419 film, melancholic 692, feel-good 318, surreal 362 ...; eşik relevance 0,8). 25 ton isteği üretildi (uygun film sayısı 65-771).
- Hakem kanıtı: 200 filmlik örnekte Wikipedia eleştiri/tema bölümü 175 filmde var (bilinenlerde 100/100, orta bilinenlerde 75/100; ortanca 1.407 karakter). Uyarı: bu bölümlerin çoğu puan özeti, tema/ton bilgisi sınırlı ("Themes"/"Style" bölümü ~14 filmde); hakem için zayıf kanıt, TMDB incelemeleri daha uygun olabilir.
- Dosyalar: `D:\reelsift-data\degerlendirme\` (`konu_listeleri.json`, `ton_istekleri.json`, `ton_etiketleri_ozet.json`, `genome_arsiv.parquet`, `elestiri_ornek.jsonl`, `movielens\`).

### 2026-11-13, profil toplu işlemi tamamlandı
- 9 parti (87.314 film) gönderimden ~15 dakika sonra bitti ve indirildi. Ayrıştırılan profil 86.828 (%99,4); hatalı 486 (%0,6; hepsi çıktının 1.200 token sınırında kesilmesi). Gerçek maliyet 24,03 dolar (girdi 116,2M + çıktı 72,9M token, toplu işlem fiyatı). Deneme profilleriyle birlikte 93.314 filmin 92.828'i için profil hazır.
- Açık: 486 filmin daha yüksek çıktı sınırıyla yeniden gönderilmesi; profil kazancının MovieLens ton anahtarıyla bağımsız doğrulanması; profillerin tam arşivde yeniden sıralama girdisi olarak ölçülmesi (faz 3).
- Dosya: `D:\reelsift-data\profil\profiller_tam.jsonl`, `hazir_profiller.jsonl`.

### 2026-11-16, profillerin tamamlanması
- Kesilen 486 profil daha yüksek çıktı sınırıyla (3.000 token) yeniden üretildi: 486/486 başarılı, maliyet ~0,30 dolar.
- Birleşik dosya: `D:\reelsift-data\profil\profiller_birlesik.jsonl`, 93.314 profil (92.374 arşiv + 940 ek film), kimlik tekrarı yok. Kaynak: toplu işlem 86.828, deneme 6.000, yeniden 486.
- Kanıt düzeyi: zengin 64.881 (%69,5), zayıf 26.181 (%28,1), yetersiz 2.232 (%2,4), alan yok 20.
- Bilinen kusurlar: Türkçe tanıtım cümlesi 1.472 profilde boş; ton alanında izinli liste dışı 194 değer (en sık "bittersweet" 75, "dark" 35). Yükleme sırasında (faz 2) liste dışı değerler ayıklanacak; boş tanıtım cümleleri için karar verilecek.
- Profil üretiminin toplam maliyeti: deneme ~6,5 dolar (hatalı ilk koşu dahil) + toplu işlem 24,03 + tamamlama 0,30 = ~31 dolar.

### 2026-11-16, profil kazancının bağımsız doğrulaması (MovieLens ton anahtarı)
- Amaç: 5. turdaki kazancın yargıç farkından şişip şişmediğini, dil modeli yargısı olmadan ve arama indeksinde bulunmayan veriyle sınamak.
- Yöntem: 25 ton isteği (Haiku 5.5 ile çözümleme, iki kolda aynı); adaylar 4. tur hattından (önekli parça + TMDB kart + kelime araması -> RRF), iki kolda aynı. Ana ölçümde aday havuzu MovieLens genome kapsamındaki 12.417 arşiv filmiyle sınırlandı (her sonuç yargılı), ilk 50 yeniden sıralandı. Uygun = etiket relevance >= 0,8; nDCG kazancı = relevance değeri. Kol A: TMDB özeti + hikâye; kol B: başa profil metni eklenmiş (5. turdaki biçim). Bu kez profiller tam arşiv için hazır (alt küme değil).
- Ana ölçüm (ortalama; P@10 / nDCG@10 / ilk 10'un ortalama relevance'ı):
  - RRF sırası (yeniden sıralamadan önce): 0,316 / 0,565 / 0,539
  - Kol A (taban yeniden sıralama): 0,208 / 0,495 / 0,485
  - Kol B (profilli yeniden sıralama): 0,364 / 0,643 / 0,612
- B - A (kazanan/kaybeden/berabere istek; ortalama fark; bootstrap %95 aralık): P@10 19/2/4, +0,156 [+0,092, +0,224]; nDCG@10 22/3/0, +0,148 [+0,107, +0,193]. Aralıklar sıfırı içermiyor.
- Yeni bulgu: ton isteklerinde taban yeniden sıralama RRF sırasından KÖTÜ (A - RRF: P@10 -0,108, nDCG -0,070; aralıklar sıfırın altında). Profilli kol RRF'yi nDCG'de geçiyor (+0,078 [+0,025, +0,133]), P@10'da fark gösterilemedi (+0,048 [-0,008, +0,104]). Yani profil kazancının bir kısmı, yeniden sıralama modelinin ton isteklerinde hikâye metniyle verdiği zararı gidermekten geliyor.
- Kesilme (model azami 1024 token): kol A'da çiftlerin %31'i kesiliyor (hikâyenin ortalama %3,8'i); kol B'de %52,7'si (hikâyenin ortalama %10,5'i). Etkisi ayrı ölçülmedi.
- İkincil ölçüm (kısıtsız tam arşiv, yargısız filmler sıradan çıkarılarak): ilk 10'da yargılı film ortalama 1-2; zayıf kanıt. B - A yalnız nDCG'de anlamlı (+0,049 [+0,029, +0,069]); P@10'da fark yok.
- Sonuç: profilin yeniden sıralama girdisinde kalması kararı bağımsız veriyle doğrulandı (yön 5. turla aynı; büyüklük daha küçük). Faz 3'e taşınan sorular: (1) ton ağırlıklı isteklerde yeniden sıralama puanı ile RRF sırasının harmanlanması denenmeli; (2) profilin başa mı sona mı konacağı ve hikâyenin kesilme etkisi ölçülmeli.
- Sınırlar: anahtar yalnız bilinen ve 2019 öncesi filmleri kapsıyor; 25 istek az (22'si filtresiz); MovieLens verisi yalnız yerelde ölçüm için kullanıldı.
- Maliyet: 25 Haiku çağrısı (~0,1 dolar, tahmin). Ham rapor: `kalite/ham/2026-11-16-ton-dogrulama.md`; betikler ve ham çıktı `D:\reelsift-data\degerlendirme\ton-dogrulama\`.

### 2026-11-17, arama hattının uygulama içinde tekrar ölçümü (faz 3)
- Amaç: deney betiklerindeki hattın uygulamaya (`apps/search`) taşınırken bozulmadığını göstermek. Kabul ölçütü: deney sayıları 3 puan içinde tutar.
- Yöntem: aynı 50 tarif ve aynı 25 ton isteği, KAYITLI Haiku çözümlemeleriyle (dil modeli çağrılmadı); komut `evaluate_search`. Deneyden farklar: veri kaynağı CSV/pickle yerine veritabanı; arşiv 92.374 yerine 93.310 film (ek filmler rakip); ad eşleme ve kelime araması veritabanındaki ad alanıyla; ülke filtresi `Film.countries` üzerinde. Vektör araması kesin (yaklaşık indeks değil).
- Sonuç (hedef -> ölçülen; ölçüm ikinci, bağımsız bir koşuda BİREBİR aynı sayıları aldı):
  - Bilinen film, belge A (TMDB özeti + hikâye), R@1 / R@10 / R@50: %72 / %92 / %94 -> %74 / %92 / %94
  - Ton, RRF sırası, P@10 / nDCG@10: 0,316 / 0,565 -> 0,312 / 0,562
  - Ton, belge A: 0,208 / 0,495 -> 0,216 / 0,501
  - Ton, belge B (profil + A): 0,364 / 0,643 -> 0,352 / 0,635
  - Bilinen film, belge B (ilk kez ölçüldü, hedef yok): %78 / %94 / %94 (yeniden sıralamadan önce RRF sırası %64 / %90 / %94)
- Karar tablosu (harman ağırlığı 0 / 0,3 / 0,5; bilinen film R@1 | ton P@10): belge A %74 / %78 / %80 | 0,216 / 0,264 / 0,284; belge B %78 / %78 / %74 | 0,352 / 0,376 / 0,364; profil sonda (B_end) %60 / %68 / %72 | 0,260 / 0,288 / 0,288.
- 2026-11-16'da açılan iki sorunun cevabı: (1) harman belge B'de küçük ve tutarsız fark veriyor (ton P@10 +0,024, bilinen film R@1 0,5 ağırlıkta -4 puan); varsayılan harman yok. (2) Profil başta kalmalı: sona konunca bilinen film R@1 %78'den %60'a düşüyor.
- Hız (RTX 4060, sıcak): toplam ortanca 2,16 sn (aday toplama 0,78 + yeniden sıralama 1,34; ilk 50 aday); ilk 100 adayla 3,03 sn. Soğuk açılışta modellerin yüklenmesi 2-4 dakika; sunucu açılışında arka planda ısındırma eklendi. Yaklaşık indeks (HNSW) sıcakken daha hızlı (0,39 sn) ama soğukken dakikalar sürebildiği için seçilmedi.
- Sınırlar: bu ölçüm yalnız ARAMAYI ve kayıtlı çözümlemelerle ölçer; dil modeli döngüde değil (uçtan uca ölçüm ayrı: `evaluate_agent`). Ölçülmeyenler: filtreli bilinen film testi, ton testinin kısıtsız havuzu, CPU yolu. 4 eşzamanlı aramada her arama 20-24 sn sürdü (nedeni belirlenmedi).
- Ham çıktı: `kalite/kanit/faz3-cikti.md`, `faz3-cikti-2.md`, `faz3-dogrulama.md`; JSON'lar konteynerde `/index/eval/`.

### 2026-11-17, kişi araması ve Türk filmleri (arama gerilemesi ve gerçek model denemeleri)
- Amaç: yönetmen / oyuncu adına göre isteklerin doğru karşılanması ve arşivin Türk filmleriyle genişlemesi sırasında mevcut arama kalitesinin bozulmadığını göstermek. Kabul ölçütü: `evaluate_search` sayıları her adımda aynı kalır (arşiv büyüdüğü için en çok 1 puan oynayabilir).
- Arşiv: 93.310 -> 94.683 film (TMDB oy sayısı en az 5 olan, arşivde olmayan 1.373 Türkiye yapımı film). Yeni filmlerin 429'unda hikâye metni var (417 Türkçe Wikipedia, 12 İngilizce), 505 parça; 1.373 kart vektörü ve profil. Profil üretimi: 1,41M giriş / 1,28M çıkış token (Haiku 5.5, doğrudan çağrı), yaklaşık 0,78 dolar (fiyat sayfasından hesap; faturadan doğrulanmadı). Türkçe filmlerde boş Türkçe ad 244 -> 0; yönetmen / oyuncu alanlarından 2.762 filmde 3.771 ham Wikidata kimliği atıldı.
- Arama ölçümü (`evaluate_search`, kayıtlı Haiku çözümlemeleri, dil modeli döngüde değil): bilinen film belge B R@1 / R@10 / R@50 = %78 / %94 / %94 ve ton (genome havuzu) belge B P@10 0,352, nDCG@10 0,635; faz 1, faz 1 düzeltme, faz 2b (yükleme sonrası) ve faz 2c'nin ilk commit'inden sonra ölçüldü, dördünde de AYNI. Faz 2c'nin sonraki commit'leri ve faz 4 arama koduna dokunmadı, yeniden ölçülmedi. Not: ton testi sabit havuzda koştuğu için yeni filmlerden etkilenmez; bilinen film testi tam arşivde koşar.
- Testler: 603 -> 789 (backend), arayüz 105.
- Gerçek modelle denemeler (çalışan sunucu, `claude-haiku-5-5`, HTTP üzerinden): faz 1 (10 + 8 istek), faz 2b (12 istek), faz 2c (11 + 22 + 18 + 3 + 6 + 8 tur), faz 4 (2 taslak + ekran görüntüleri). Son durumda kişi isteklerinde sayılar veritabanıyla tutuyor: David Lynch en iyi 3 -> 3 / 3 Lynch ve en yüksek puanlı üçü; Zeki Demirkubuz 12 / 12; Hitchcock 45; Türkan Şoray 46 (taslakta ilk 20); Kemal Sunal 81. "N tane daha ekle" 8 / 8 çalıştırmada mevcut filmleri koruyarak ekledi. Kayıtlı cevaplarda iç ifade sızıntısı son beş denemede 0. Tur süresi 2-56 sn (soru cevabı ~5 sn, taslak 11-56 sn).
- Sınırlar: `evaluate_agent` tam kümesi bu işte de koşulmadı (uçtan uca ölçüm yok; denemeler örnek isteklerle, çoğu tek çalıştırma). Hikâyesi olmayan 944 yeni film tema aramasına girmiyor (300 karakter kuralı); kişi aramasında ve adıyla istendiğinde çıkıyor. Bilinen açık kusurlar `BUGS.md`'de (11-19).
- Ham çıktılar geliştirme kayıtlarında tutuldu; bu depoya alınmadı.

### 2026-11-18, uçtan uca ölçüm: agent tam küme (faz 7, Haiku 5.5)
- Amaç: dil modeli döngüdeyken (istek -> çözümleme -> arama -> değerlendirme -> gerekçeli taslak) sistemin ilk tam ölçümü. Önceki ölçümler yalnız aramayı, kayıtlı çözümlemelerle ölçüyordu.
- Yöntem: komut `evaluate_agent --set known50 --set konu30 --set tone25 --model claude-haiku-5-5 --concurrency 1 --budget 3`; 105 istek, her biri gerçek bir tur (canlı çözümleme, filtreler dahil). Kod `main` `204e674`, arşiv 94.683 film. Ayrık konteynerde, sunucu durdurulmuşken koşuldu (bellek).
- Sonuç (105 / 105 tur hatasız bitti, yeniden deneme yok):
  - Bilinen film (50 tarif): hedef film taslakta %96 (48 / 50; bir turda taslak çıkmadı, ıska sayıldı), taslakta ortalama sırası 1,02. Aramanın ilk çağrısında R@1 / R@10 / R@50 = %82 / %90 / %92. Taslakta ortalama 2,8 film.
  - Konu (30 istek, Wikipedia listeleri): taslak kesinliği %62, ALT SINIR (listede olmayan ama konuya uyan film yanlış sayılır). Taslakta ortalama 10,0 film.
  - Ton (25 istek, MovieLens genome): kapsamdaki filmlerde kesinlik %49. 250 taslak filminin 98'i genome kapsamında, 152'si kapsam dışı (yargılanmadı); yargılanamayan tur 0.
  - Kaynak alıntısı: üç kümede de alıntıların %100'ü kaynak metinde birebir bulundu; alıntısı tutmadığı için düşen film ortalaması 0,0.
- Süre: tur ortancası bilinen filmde 68,3 sn (en uzun 371,6 sn), konuda 39,2 sn (en uzun 47,0), tonda 38,7 sn (en uzun 49,4). Koşunun tamamı 1 sa 40 dk (17:18-18:58).
- Maliyet: 1,8013 dolar (komutun kendi hesabı; faturadan doğrulanmadı). İstek başına bilinen film 0,021, konu 0,0138, ton 0,0134 dolar.
- Sınırlar: tek koşu, tek model; tekrarlanırlık ölçülmedi. R@k sayıları `evaluate_search` sayılarıyla (belge B %78 / %94 / %94) doğrudan karşılaştırılamaz: orada kayıtlı çözümleme ve filtresiz arama, burada canlı çözümleme ve filtreler var. Ton kesinliği taslak filmlerinin yalnız %39'u (98 / 250) üzerinden hesaplandı. Gerekçe cümlesinin doğruluğu ölçülmüyor (yalnız alıntı). Logda bazı turlarda cevap adımında iç ifade / yabancı dil uyarısı var (cümle atılıp cevap teslim edilmiş); kaç turda olduğu sayılmadı. Sonnet karşılaştırması henüz koşulmadı.
- Ham çıktı: `kalite/kanit/olcum-haiku-2026-11-18.log` (özet log sonunda); JSON `D:\reelsift-data\olcum\tam-haiku-2026-11-18.json` (konteynerde `/index/eval/agent/tam-haiku-2026-11-18.json`).
