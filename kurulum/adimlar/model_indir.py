"""Arama modellerini sabit surumle ve yalniz gereken dosyalarla indirir ve DOGRULAR (backend konteynerinde calisir).

Hugging Face onbellek duzeni /models/hub altina yazilir (HF_HOME=/models). Sunucu cevrimdisi
(HF_HUB_OFFLINE=1) acildigi icin `refs/main` dosyasi sabit surumu gostermelidir; sabit surumle
indirmede huggingface_hub bunu yazmaz, burada elle yazilir.

Dogrulama KONTEYNER ICINDE yapilir: snapshot altindaki Linux simgesel baglari izlenir, her dosyanin var
oldugu ve boyutu denetlenir (Windows tarafi bag dosyalarini 0 bayt gorur, ona guvenilmez). Sonuc
/models/hazir.json olarak yazilir; kurulum betigi yalniz bu isaret dosyasina bakar. Dosyalar zaten
tamsa hic indirme yapilmaz (hazir.json yoksa yalnizca uretilir).

Cikis kodlari: 0 tamam, 1 dogrulanamadi (eksik / boyut), 2 ag hatasi (indirme kesildi), 3 baska hata.
"""

import json
import os
import sys
import threading
import time

CACHE = os.path.join(os.environ.get("HF_HOME", "/models"), "hub")
HAZIR = os.path.join(os.environ.get("HF_HOME", "/models"), "hazir.json")

# (model, surum, dosyalar, bilinen en az boyutlar)
MODELLER = [
    (
        "BAAI/bge-m3",
        "5617a9f61b028005a4858fdac845db406aefb181",
        [
            "config.json",
            "config_sentence_transformers.json",
            "modules.json",
            "sentence_bert_config.json",
            "1_Pooling/config.json",
            "pytorch_model.bin",
            "sentencepiece.bpe.model",
            "special_tokens_map.json",
            "tokenizer.json",
            "tokenizer_config.json",
        ],
        {"pytorch_model.bin": 2271145830},
    ),
    (
        "BAAI/bge-reranker-v2-m3",
        "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e",
        [
            "config.json",
            "model.safetensors",
            "sentencepiece.bpe.model",
            "special_tokens_map.json",
            "tokenizer.json",
            "tokenizer_config.json",
        ],
        {"model.safetensors": 2271071852},
    ),
]


def model_klasoru(repo):
    return os.path.join(CACHE, "models--" + repo.replace("/", "--"))


def dogrula(repo, revision, patterns, boyutlar):
    """Dosyalarin var oldugunu (baglar izlenerek) ve boyutlarini denetler. (dosya_sayisi, bayt, eksik)."""
    snapshot = os.path.join(model_klasoru(repo), "snapshots", revision)
    eksik = []
    toplam = 0
    sayi = 0
    for p in patterns:
        yol = os.path.join(snapshot, p)
        try:
            boyut = os.path.getsize(yol) if os.path.isfile(yol) else -1
        except OSError:
            boyut = -1
        beklenen = boyutlar.get(p)
        if boyut <= 0 or (beklenen is not None and boyut != beklenen):
            eksik.append(p + " (boyut " + str(boyut) + ")")
            continue
        sayi += 1
        toplam += boyut
    return sayi, toplam, eksik


def ref_yaz(repo, revision):
    refs = os.path.join(model_klasoru(repo), "refs")
    os.makedirs(refs, exist_ok=True)
    with open(os.path.join(refs, "main"), "w", encoding="ascii") as f:
        f.write(revision)


def hazir_yaz(sonuclar):
    veri = {
        "surum": 1,
        "modeller": sonuclar,
        "toplam_bayt": sum(s["bayt"] for s in sonuclar),
        "zaman": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    gecici = HAZIR + ".tmp"
    with open(gecici, "w", encoding="ascii") as f:
        json.dump(veri, f, indent=2)
    os.replace(gecici, HAZIR)


def ilerleme_yaz(durdur):
    """Konteyner icinden gercek bayt sayisini her 3 sn'de gunluge yazar (Windows tarafi buyuyen dosyayi gec gorebilir)."""
    while not durdur.wait(3):
        toplam = 0
        for kok, _, dosyalar in os.walk(CACHE):
            for d in dosyalar:
                yol = os.path.join(kok, d)
                if os.path.islink(yol):
                    continue
                try:
                    toplam += os.path.getsize(yol)
                except OSError:
                    pass
        print("ILERLEME " + str(toplam), flush=True)


def ag_hatasi_mi(e):
    ad = type(e).__module__ + "." + type(e).__name__
    for parca in ("requests", "httpx", "urllib3", "LocalEntryNotFound", "Timeout", "ConnectionError", "socket"):
        if parca in ad:
            return True
    return isinstance(e, (ConnectionError, TimeoutError))


def main() -> int:
    if os.path.exists(HAZIR):
        os.remove(HAZIR)
    durdur = threading.Event()
    threading.Thread(target=ilerleme_yaz, args=(durdur,), daemon=True).start()
    sonuclar = []
    try:
        for repo, revision, patterns, boyutlar in MODELLER:
            sayi, bayt, eksik = dogrula(repo, revision, patterns, boyutlar)
            if eksik:
                print("INDIRILIYOR " + repo + " @ " + revision[:7], flush=True)
                from huggingface_hub import snapshot_download

                snapshot_download(
                    repo_id=repo,
                    revision=revision,
                    allow_patterns=patterns,
                    cache_dir=CACHE,
                )
                sayi, bayt, eksik = dogrula(repo, revision, patterns, boyutlar)
            else:
                print("ZATEN VAR " + repo + " (indirme yok)", flush=True)
            ref_yaz(repo, revision)
            if eksik:
                print("EKSIK " + repo + ": " + ", ".join(eksik), flush=True)
                return 1
            print("TAMAM " + repo + " dosya=" + str(sayi) + " bayt=" + str(bayt), flush=True)
            sonuclar.append(
                {"model": repo, "surum": revision, "dosya_sayisi": sayi, "bayt": bayt}
            )
        hazir_yaz(sonuclar)
        print("HAZIR hazir.json yazildi", flush=True)
        return 0
    except Exception as e:  # kullaniciya sade mesaj icin cikis kodu ayrimi
        print("HATA " + type(e).__name__ + ": " + str(e)[:300], flush=True)
        return 2 if ag_hatasi_mi(e) else 3
    finally:
        durdur.set()


if __name__ == "__main__":
    sys.exit(main())
