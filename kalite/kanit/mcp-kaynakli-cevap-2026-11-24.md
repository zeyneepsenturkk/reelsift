# Bilgi yolu: gerçek deneme (Claude Haiku + Wikipedia)

Ayrık konteyner, SEARCH_WARMUP=0, sunucu açılmadı. Betik answer düğümünün `_source_for` (konu çıkarma + MCP aracı) ve `_stream` (cevap) adımlarını gerçek modelle çağırır; kaynak satırı kodla eklenir. Konu satırı yoksa konu null döndü.

```
## SORU: Zeki Demirkubuz kimdir?
KONU (modelin cikardigi): Zeki Demirkubuz
ARAC: bulundu baslik=Zeki Demirkubuz dil=tr adres=https://tr.wikipedia.org/wiki/Zeki_Demirkubuz
OZET: Zeki Demirkubuz, Türk film yönetmeni, senarist, yapımcı ve oyuncu.
CEVAP:
Zeki Demirkubuz, Türk film yönetmeni, senarist, yapımcı ve oyuncu olarak tanınan bir sinema adamı. Elimde onun hakkında bundan fazla bilgi yok, bu yüzden filmografisi ya da üslubu hakkında kesin bir şey söyleyemem. İstersen onun filmlerini arşivde arayıp bir seçki taslağı hazırlayabilirim.

Kaynak: Wikipedia, https://tr.wikipedia.org/wiki/Zeki_Demirkubuz
SURE: konu+arac 1.4 sn, toplam 2.9 sn

## SORU: Film noir ne demek?
KONU (modelin cikardigi): Film noir
ARAC: bulundu baslik=Kara film dil=tr adres=https://tr.wikipedia.org/wiki/Kara_film
OZET: Kara film, öncelikle kahramanlarını çürümüş ve itici algılanabilecek bir dünyanın içine yerleştiren Hollywood suç filmlerini tanımlamak için kullanılan bir sinema terimidir. Hollywood'un klasik kara film dönemi, 1940'ların başından 1950'lerin sonuna kadar uzanır. Bu dönemin az ışıklı, siyah beyaz çe
CEVAP:
Kara film, kahramanlarını çürümüş ve itici bir dünyanın içine yerleştiren Hollywood suç filmlerini anlatmak için kullanılan bir sinema terimidir. Klasik dönemi 1940'ların başından 1950'lerin sonuna kadar sürer ve bu filmler genellikle az ışıklı, siyah beyaz çekilmiştir. Görsel anlayışı Alman Dışavurumcu sinemasından etkilenmiştir. Türün kökleri de Büyük Bunalım yıllarında Amerika Birleşik Devletleri'nde ortaya çıkan suç filmlerine uzanır.

Kara film, Türkçede "film noir" olarak da bilinir.

Kaynak: Wikipedia, https://tr.wikipedia.org/wiki/Kara_film
SURE: konu+arac 1.1 sn, toplam 2.9 sn

## SORU: Merhaba, nasılsın?
ARAC: cagrilmadi ya da bulunamadi (kaynak yok)
CEVAP:
Merhaba, iyiyim, teşekkür ederim. Bir film seçkisi üzerinde çalışmaya hazırım. İstersen bir yönetmen, bir oyuncu ya da bir tema söyle, arşivde ne olduğuna bakıp sana **taslak** hazırlayayım.
SURE: konu+arac 1.4 sn, toplam 2.5 sn

```
