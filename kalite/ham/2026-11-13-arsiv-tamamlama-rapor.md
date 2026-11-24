# Arsiv raporu (2026-11-13, 20:47-21:30, ~43 dk)
A1: discover 500 sayfa -> 9836 benzersiz film (sayfa kaymasi nedeniyle 10.000 degil). Eksik (CSV tmdb_id'de yok): ilk1000=23, ilk5000=326, tum=941.
A2: eksik_filmler.jsonl 941 satir; plot'lu 695, plot'suz 246 (QID yok 28, enwiki sayfasi/Plot bolumu yok kalani). Id ile arsivde zaten olan: 5 (in_archive_by_id=true). Baslik+yil CSV'de olan (id eslesmesi yok): 6.
B1: 300 ornek (150 vote>=100, 150 <100): iyilesen 19 = %6.3 (vote>=100: 17=%11.3; <100: 2=%1.3); Plot bolumu yok: 0; iyilesenlerde medyan eski/yeni 300/3900. Esik %15 altinda -> B2 sadece vote>=100.
B2+B3: 1166 secildi (1114 kisa+vote>=100, B3 dahil), 1166 islendi, 139 uzadi (>=2x ve >=300 kar); medyan eski/yeni 302 -> 3913.
C1: 375/dilim. >=1 inceleme: <20 %6.1, 20-100 %17.3, 100-1000 %44.0, >1000 %88.5. Ort inceleme/film (incelemesi olanlarda) 1.04/1.18/1.55/4.45. Medyan uzunluk 1252/1276/1054/868 karakter. Dil: TMDB alan vermiyor; ASCII sezgisi ile ~%99 Latin/Ingilizce.
C2: esik>=%20 -> dilim 100-1000 ve >1000 (vote>=100): 18172 film islendi, 9843 filmde inceleme, 20485 inceleme (film basina max 5, ilk 3000 karakter, yazar saklanmadi). Sadece sayfa 1 (20) okundu.
Hata: Wikipedia ilk UA ile 403 verdi (UA degistirildi, veri yeniden cekildi); TMDB 0 hata.
