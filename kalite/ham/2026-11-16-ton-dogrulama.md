# 2026-11-16 ton dogrulama (ham)
Cevap anahtari: MovieLens Tag Genome (43 etiket, 25 ton istegi, esik 0.8; kazanc = istegin etiketlerinin max relevance degeri; ek kisit (tur/yil/ulke) saglamayan film kazanc 0). Genome kapsami 12.417 arsiv filmi. Sorgu cozumleme: Haiku 5.5 (effort low), iki kol ayni. Adaylar ayni (4. tur hatti, RRF, ilk 50). Kol A: ozet+hikaye; Kol B: profil metni basa eklenir (5. tur ile ayni ptext). R@50 = ilk 50'deki uygun / min(50, uygun sayisi); aday kumesi ayni oldugu icin uc kolda ayni. nDCG ideali = tum yargili filmlerdeki en iyi 10. Betikler: D:\reelsift-data\degerlendirme\ton-dogrulama\ (s1_haiku.py, s2_run.py, s3_score.py, lib_t.py; ham: haiku_ton.json, s2_sonuc.pkl).
Sapma: onceki python ortami silinmisti; ton-dogrulama\venv altina torch 2.14.1+cu126 + sentence-transformers kuruldu (pip onbellegi D'de).

## ANA OLCUM: havuz genome kapsamli ~12.4k film, ilk 50 yeniden siralama

### Ortalamalar (25 istek)
| kol | P@10 | nDCG@10 | ortRel@10 | R@50 |
|---|---|---|---|---|
| rrf | 0.3160 | 0.5654 | 0.5388 | 0.1992 |
| A | 0.2080 | 0.4950 | 0.4852 | 0.1992 |
| B | 0.3640 | 0.6432 | 0.6115 | 0.1992 |

### Eslestirilmis karsilastirma (kazanan/kaybeden/berabere; ort. fark; bootstrap %95, 10.000 ornekleme)
| cift | olcut | K/Kb/B | ort fark | %95 GA | yorum |
|---|---|---|---|---|---|
| B - A | P@10 | 19/2/4 | +0.1560 | [+0.0920, +0.2240] | SIFIRI ICERMIYOR |
| B - A | nDCG@10 | 22/3/0 | +0.1482 | [+0.1073, +0.1929] | SIFIRI ICERMIYOR |
| B - A | ortRel@10 | 21/4/0 | +0.1263 | [+0.0879, +0.1660] | SIFIRI ICERMIYOR |
| A - rrf | P@10 | 3/12/10 | -0.1080 | [-0.1760, -0.0440] | SIFIRI ICERMIYOR |
| A - rrf | nDCG@10 | 9/16/0 | -0.0704 | [-0.1175, -0.0246] | SIFIRI ICERMIYOR |
| A - rrf | ortRel@10 | 7/18/0 | -0.0536 | [-0.0955, -0.0125] | SIFIRI ICERMIYOR |
| B - rrf | P@10 | 11/6/8 | +0.0480 | [-0.0080, +0.1040] | fark gosterilemedi (aralik sifiri iciyor) |
| B - rrf | nDCG@10 | 19/6/0 | +0.0778 | [+0.0253, +0.1334] | SIFIRI ICERMIYOR |
| B - rrf | ortRel@10 | 21/4/0 | +0.0727 | [+0.0291, +0.1154] | SIFIRI ICERMIYOR |

### Istek basina (P@10 rrf/A/B | nDCG@10 rrf/A/B | ortRel rrf/A/B | uygun sayisi | havuz | yargili ilk10 rrf/A/B)
| id | istek | P@10 | nDCG@10 | ortRel@10 | n_uygun | yargili ilk10 |
|---|---|---|---|---|---|---|
| ton_01 | heartwarming, uplifting feel-good films | 0.10 / 0.10 / 0.20 | 0.44 / 0.52 / 0.65 | 0.41 / 0.53 / 0.62 | 402 | 10 / 10 / 10 |
| ton_02 | melancholic films with a quiet sadness | 0.70 / 0.20 / 0.70 | 0.81 / 0.62 / 0.87 | 0.79 / 0.58 / 0.83 | 704 | 10 / 10 / 10 |
| ton_03 | bleak, hopeless films | 0.10 / 0.10 / 0.10 | 0.31 / 0.47 / 0.44 | 0.31 / 0.48 / 0.46 | 419 | 10 / 10 / 10 |
| ton_04 | tense, suspenseful films that keep you on  | 0.30 / 0.30 / 0.30 | 0.53 / 0.38 / 0.62 | 0.52 / 0.43 / 0.58 | 771 | 10 / 10 / 10 |
| ton_05 | surreal, dreamlike films | 0.70 / 0.50 / 0.80 | 0.86 / 0.73 / 0.87 | 0.82 / 0.70 / 0.87 | 373 | 10 / 10 / 10 |
| ton_06 | quirky, offbeat films | 0.10 / 0.10 / 0.20 | 0.54 / 0.44 / 0.52 | 0.50 / 0.44 / 0.43 | 152 | 10 / 10 / 10 |
| ton_07 | claustrophobic films | 0.30 / 0.30 / 0.40 | 0.49 / 0.57 / 0.68 | 0.50 / 0.48 / 0.66 | 153 | 10 / 10 / 10 |
| ton_08 | bittersweet films | 0.30 / 0.20 / 0.50 | 0.51 / 0.49 / 0.69 | 0.45 / 0.48 / 0.57 | 217 | 10 / 10 / 10 |
| ton_09 | gritty crime films | 0.10 / 0.10 / 0.00 | 0.37 / 0.41 / 0.38 | 0.31 / 0.34 / 0.33 | 117 | 10 / 10 / 10 |
| ton_10 | nostalgic films | 0.10 / 0.10 / 0.40 | 0.33 / 0.38 / 0.62 | 0.37 / 0.32 / 0.57 | 95 | 10 / 10 / 10 |
| ton_11 | disturbing films | 0.20 / 0.10 / 0.20 | 0.60 / 0.49 / 0.65 | 0.56 / 0.45 / 0.59 | 212 | 10 / 10 / 10 |
| ton_12 | whimsical, fairytale-like films | 0.20 / 0.10 / 0.20 | 0.60 / 0.45 / 0.58 | 0.51 / 0.44 / 0.53 | 101 | 10 / 10 / 10 |
| ton_13 | meditative, contemplative films | 0.70 / 0.30 / 0.90 | 0.76 / 0.59 / 0.91 | 0.77 / 0.58 / 0.91 | 381 | 10 / 10 / 10 |
| ton_14 | eerie, creepy atmospheric horror films | 0.30 / 0.00 / 0.30 | 0.54 / 0.42 / 0.57 | 0.50 / 0.42 / 0.54 | 371 | 10 / 10 / 10 |
| ton_15 | dark, depressing, hopeless films | 0.00 / 0.10 / 0.10 | 0.38 / 0.45 / 0.38 | 0.35 / 0.44 / 0.38 | 324 | 10 / 10 / 10 |
| ton_16 | atmospheric films from before 1970 | 0.20 / 0.00 / 0.10 | 0.72 / 0.38 / 0.54 | 0.65 / 0.38 / 0.47 | 80 | 10 / 10 / 10 |
| ton_17 | cerebral, thought-provoking mind-bending f | 0.80 / 0.40 / 0.60 | 0.82 / 0.55 / 0.66 | 0.77 / 0.58 / 0.72 | 401 | 10 / 10 / 10 |
| ton_18 | heartbreaking, touching tearjerker films | 0.50 / 0.20 / 0.40 | 0.59 / 0.49 / 0.67 | 0.57 / 0.49 / 0.68 | 433 | 10 / 10 / 10 |
| ton_19 | absurd, dark-humor films | 0.20 / 0.30 / 0.50 | 0.59 / 0.60 / 0.74 | 0.53 / 0.59 / 0.71 | 383 | 10 / 10 / 10 |
| ton_20 | stylish fast-paced action films | 0.10 / 0.10 / 0.40 | 0.23 / 0.20 / 0.68 | 0.27 / 0.23 / 0.61 | 262 | 10 / 10 / 10 |
| ton_21 | sweet, cute family-friendly films | 0.00 / 0.10 / 0.20 | 0.14 / 0.16 / 0.34 | 0.18 / 0.20 / 0.35 | 65 | 10 / 10 / 10 |
| ton_22 | bizarre, hallucinatory experimental films | 0.60 / 0.60 / 0.60 | 0.89 / 0.72 / 0.80 | 0.86 / 0.68 / 0.73 | 376 | 10 / 10 / 10 |
| ton_23 | brutal, visceral revenge films | 0.40 / 0.10 / 0.20 | 0.60 / 0.56 / 0.72 | 0.56 / 0.55 / 0.66 | 336 | 10 / 10 / 10 |
| ton_24 | tense, intense films from 2010 onward | 0.40 / 0.40 / 0.30 | 0.72 / 0.54 / 0.65 | 0.66 / 0.59 / 0.67 | 214 | 10 / 10 / 10 |
| ton_25 | French or Italian melancholic, reflective  | 0.50 / 0.40 / 0.50 | 0.76 / 0.77 / 0.86 | 0.77 / 0.73 / 0.85 | 283 | 10 / 10 / 10 |

## IKINCIL OLCUM: kisitsiz tam arsiv ilk 50, yargisiz filmler siradan cikarildi

### Ortalamalar (25 istek)
| kol | P@10 | nDCG@10 | ortRel@10 | R@50 |
|---|---|---|---|---|
| rrf | 0.2240 | 0.4679 | 0.4137 | 0.0512 |
| A | 0.2400 | 0.4603 | 0.4268 | 0.0512 |
| B | 0.2400 | 0.5092 | 0.4339 | 0.0512 |

### Eslestirilmis karsilastirma (kazanan/kaybeden/berabere; ort. fark; bootstrap %95, 10.000 ornekleme)
| cift | olcut | K/Kb/B | ort fark | %95 GA | yorum |
|---|---|---|---|---|---|
| B - A | P@10 | 1/1/23 | -0.0000 | [-0.0120, +0.0120] | fark gosterilemedi (aralik sifiri iciyor) |
| B - A | nDCG@10 | 20/3/2 | +0.0489 | [+0.0292, +0.0688] | SIFIRI ICERMIYOR |
| B - A | ortRel@10 | 4/2/19 | +0.0071 | [-0.0008, +0.0205] | fark gosterilemedi (aralik sifiri iciyor) |
| A - rrf | P@10 | 4/1/20 | +0.0160 | [-0.0040, +0.0400] | fark gosterilemedi (aralik sifiri iciyor) |
| A - rrf | nDCG@10 | 8/17/0 | -0.0075 | [-0.0278, +0.0150] | fark gosterilemedi (aralik sifiri iciyor) |
| A - rrf | ortRel@10 | 6/2/17 | +0.0131 | [+0.0020, +0.0266] | SIFIRI ICERMIYOR |
| B - rrf | P@10 | 4/1/20 | +0.0160 | [-0.0040, +0.0400] | fark gosterilemedi (aralik sifiri iciyor) |
| B - rrf | nDCG@10 | 17/8/0 | +0.0413 | [+0.0180, +0.0665] | SIFIRI ICERMIYOR |
| B - rrf | ortRel@10 | 6/2/17 | +0.0202 | [+0.0039, +0.0388] | SIFIRI ICERMIYOR |

### Istek basina (P@10 rrf/A/B | nDCG@10 rrf/A/B | ortRel rrf/A/B | uygun sayisi | havuz | yargili ilk10 rrf/A/B (kisitsiz ilk 10'daki genome kapsamli film))
| id | istek | P@10 | nDCG@10 | ortRel@10 | n_uygun | yargili ilk10 |
|---|---|---|---|---|---|---|
| ton_01 | heartwarming, uplifting feel-good films | 0.20 / 0.20 / 0.20 | 0.41 / 0.37 / 0.43 | 0.30 / 0.30 / 0.30 | 402 | 1 / 2 / 0 |
| ton_02 | melancholic films with a quiet sadness | 0.20 / 0.20 / 0.20 | 0.44 / 0.42 / 0.42 | 0.29 / 0.29 / 0.29 | 704 | 0 / 1 / 1 |
| ton_03 | bleak, hopeless films | 0.10 / 0.10 / 0.10 | 0.27 / 0.30 / 0.37 | 0.25 / 0.25 / 0.25 | 419 | 1 / 1 / 1 |
| ton_04 | tense, suspenseful films that keep you on  | 0.30 / 0.30 / 0.30 | 0.52 / 0.53 / 0.57 | 0.53 / 0.51 / 0.50 | 771 | 2 / 0 / 2 |
| ton_05 | surreal, dreamlike films | 0.70 / 0.70 / 0.70 | 0.87 / 0.84 / 0.87 | 0.82 / 0.82 / 0.82 | 373 | 2 / 0 / 1 |
| ton_06 | quirky, offbeat films | 0.10 / 0.10 / 0.10 | 0.59 / 0.59 / 0.59 | 0.54 / 0.59 / 0.59 | 152 | 3 / 1 / 1 |
| ton_07 | claustrophobic films | 0.20 / 0.30 / 0.30 | 0.44 / 0.43 / 0.55 | 0.37 / 0.47 / 0.48 | 153 | 3 / 2 / 3 |
| ton_08 | bittersweet films | 0.20 / 0.20 / 0.20 | 0.48 / 0.43 / 0.55 | 0.44 / 0.44 / 0.44 | 217 | 2 / 2 / 0 |
| ton_09 | gritty crime films | 0.00 / 0.00 / 0.00 | 0.33 / 0.33 / 0.32 | 0.27 / 0.27 / 0.27 | 117 | 2 / 0 / 3 |
| ton_10 | nostalgic films | 0.20 / 0.20 / 0.20 | 0.38 / 0.33 / 0.48 | 0.37 / 0.37 / 0.37 | 95 | 2 / 1 / 1 |
| ton_11 | disturbing films | 0.00 / 0.00 / 0.00 | 0.30 / 0.32 / 0.31 | 0.24 / 0.24 / 0.24 | 212 | 0 / 1 / 1 |
| ton_12 | whimsical, fairytale-like films | 0.20 / 0.40 / 0.30 | 0.63 / 0.65 / 0.70 | 0.53 / 0.60 / 0.63 | 101 | 3 / 1 / 3 |
| ton_13 | meditative, contemplative films | 0.40 / 0.40 / 0.40 | 0.64 / 0.62 / 0.72 | 0.62 / 0.67 / 0.67 | 381 | 4 / 3 / 3 |
| ton_14 | eerie, creepy atmospheric horror films | 0.20 / 0.20 / 0.20 | 0.44 / 0.35 / 0.47 | 0.31 / 0.31 / 0.31 | 371 | 0 / 0 / 0 |
| ton_15 | dark, depressing, hopeless films | 0.10 / 0.00 / 0.00 | 0.31 / 0.37 / 0.39 | 0.37 / 0.35 / 0.35 | 324 | 1 / 2 / 2 |
| ton_16 | atmospheric films from before 1970 | 0.30 / 0.30 / 0.30 | 0.65 / 0.63 / 0.63 | 0.55 / 0.55 / 0.55 | 80 | 2 / 0 / 3 |
| ton_17 | cerebral, thought-provoking mind-bending f | 0.20 / 0.20 / 0.20 | 0.37 / 0.28 / 0.35 | 0.21 / 0.21 / 0.21 | 401 | 2 / 1 / 0 |
| ton_18 | heartbreaking, touching tearjerker films | 0.10 / 0.10 / 0.10 | 0.12 / 0.15 / 0.15 | 0.10 / 0.10 / 0.10 | 433 | 2 / 1 / 0 |
| ton_19 | absurd, dark-humor films | 0.20 / 0.30 / 0.30 | 0.47 / 0.65 / 0.66 | 0.52 / 0.61 / 0.61 | 383 | 2 / 2 / 3 |
| ton_20 | stylish fast-paced action films | 0.10 / 0.10 / 0.10 | 0.26 / 0.15 / 0.20 | 0.15 / 0.15 / 0.15 | 262 | 1 / 0 / 3 |
| ton_21 | sweet, cute family-friendly films | 0.00 / 0.00 / 0.00 | 0.13 / 0.13 / 0.19 | 0.12 / 0.12 / 0.12 | 65 | 3 / 3 / 3 |
| ton_22 | bizarre, hallucinatory experimental films | 0.60 / 0.60 / 0.60 | 0.81 / 0.79 / 0.81 | 0.76 / 0.76 / 0.76 | 376 | 3 / 2 / 2 |
| ton_23 | brutal, visceral revenge films | 0.20 / 0.20 / 0.20 | 0.53 / 0.50 / 0.58 | 0.51 / 0.51 / 0.51 | 336 | 3 / 0 / 7 |
| ton_24 | tense, intense films from 2010 onward | 0.40 / 0.40 / 0.40 | 0.62 / 0.61 / 0.56 | 0.48 / 0.48 / 0.48 | 214 | 2 / 0 / 1 |
| ton_25 | French or Italian melancholic, reflective  | 0.40 / 0.50 / 0.60 | 0.69 / 0.73 / 0.87 | 0.68 / 0.69 / 0.84 | 283 | 2 / 2 / 3 |

Kisitsiz ilk 10'da ortalama yargili film: rrf 1.92, A 1.12, B 1.88 (10 uzerinden)
Not: yargisiz filmler atildigi icin P@10 ilk 10 yargili filmin icinde olculur; kapsam yanliligi (bilinen filmler) var.

## Kesilme (reranker azami uzunluk 1024 token, ana olcum, 25x50 cift)
| kol | cift basina ort. token | kesilen cift orani | ort. kesilen token | ort. doc kesilme orani | ort. hikaye kesilme orani |
|---|---|---|---|---|---|
| A | 840 | 0.310 | 45.2 | 0.036 | 0.038 |
| B | 999 | 0.527 | 113.1 | 0.086 | 0.105 |

Adaylardan profili olanlar (ort.): 0.999

## Sorgu cozumleme (Haiku 5.5, low)
| id | en_query | filtre |
|---|---|---|
| ton_01 | heartwarming, uplifting films that leave the viewer feeling hopeful an | [] {} |
| ton_02 | Melancholic, gently sorrowful films that evoke a soft, bittersweet sad | [] {} |
| ton_03 | A bleak, hopeless, heavy-hearted film with a gloomy and oppressive atm | [] {} |
| ton_04 | A tense, suspenseful thriller that keeps its gripping, nerve-wracking  | [] {} |
| ton_05 | Surreal, dreamlike films with an ethereal, hypnotic atmosphere where r | [] {} |
| ton_06 | Quirky, offbeat films with a distinctive, idiosyncratic sense of humor | [] {} |
| ton_07 | Claustrophobic films where a character is trapped and confined within  | [] {} |
| ton_08 | Bittersweet films that mix tender, joyful moments with melancholy and  | [] {} |
| ton_09 | Gritty, harsh crime films with a dark, raw and violent atmosphere. | [] {} |
| ton_10 | Nostalgic films that evoke longing for the past, with warm, wistful me | [] {} |
| ton_11 | Disturbing, unsettling psychological films that create a lingering sen | [] {} |
| ton_12 | Dreamlike, fairytale-like films with subtle, understated humor and whi | [] {} |
| ton_13 | Calm, meditative, contemplative films that provoke thought through slo | [] {} |
| ton_14 | Eerie, unsettling horror films with a creepy, suspenseful atmosphere t | [] {} |
| ton_15 | dark, bleak and emotionally devastating depressing films that leave th | [] {} |
| ton_16 | Atmospheric films made before 1970 with strong mood, mystery, and visu | ['ymax'] {'year_max': 1969} |
| ton_17 | Clever, mind-bending psychological thriller films that challenge the v | [] {} |
| ton_18 | heartbreaking and tearjerking emotional drama films that move the audi | [] {} |
| ton_19 | Absurdist black comedy films filled with dark humor and surreal, bizar | [] {} |
| ton_20 | Stylish, stylized, fast-paced action films with slick choreography, ki | [] {} |
| ton_21 | A heartwarming, sweet and charming family film that children and paren | [] {} |
| ton_22 | Surreal, experimental and hallucinatory films with dreamlike, disorien | [] {} |
| ton_23 | Hard-hitting, merciless films full of raw, visceral, instinctive viole | [] {} |
| ton_24 | Tense, intense psychological thrillers released after 2010 that keep v | ['ymin'] {'year_min': 2010} |
| ton_25 | Melancholic and contemplative art-house films produced in France or It | ['ulke'] {'countries': ['France', 'Italy']} |

Haiku token: girdi 13214, cikti 13195