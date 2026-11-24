"""Uçtan uca ölçüm istekleri: üç cevap anahtarı, belirlenimci örnekleme.

İstek metni YALNIZ editörün yazacağı Türkçe cümledir; cevap anahtarı (hedef film, cevap listesi,
etiket kazançları) isteğin yanında ayrı alanlarda taşınır ve metne hiçbir şey eklenmez.
Veri yalnız `/data`'dan okunur, repoya ve veritabanına girmez.
"""

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings

from apps.core.exceptions import ServiceError
from apps.films.models import Film
from apps.search.services import evaluation

SET_NAMES = ("known50", "konu30", "tone25")
KONU_LISTS = "degerlendirme/konu_listeleri.json"
# Türkçe istek dosyaları cp1254 ile kaydedilmiş (utf-8 değil); bozuk harf sessizce geçmesin diye
# kodlama açıkça verilir.
CP1254 = "cp1254"
SAMPLE_SEED = "agent-eval-v1"


@dataclass
class EvalRequest:
    set_name: str
    key: str  # küme içinde tekil ve dosyalar arasında sabit; devam bununla eşleşir
    text: str
    target_wikidata_id: str | None = None  # known50
    target_film_id: int | None = None
    known: bool | None = None
    answer_qids: frozenset[str] = frozenset()  # konu30
    answer_in_db: int | None = None  # cevap listesindeki kaç kimliğin filmi veritabanında var
    gains: dict[int, float] = field(default_factory=dict)  # tone25: film kimliği -> kazanç
    relevant: frozenset[int] = frozenset()


def _read_json(path: Path, encoding: str):
    if not path.exists():
        raise ServiceError(f"Değerlendirme verisi yok: {path}", "eval_data_missing", 500)
    return json.loads(path.read_bytes().decode(encoding))


def _eval_root() -> Path:
    return Path(settings.SEARCH["eval_data_dir"])


def load_known50_requests() -> list[EvalRequest]:
    """İstek metni: kayıtlı Türkçe tarif (`tr` alanı) olduğu gibi."""
    return [
        EvalRequest(
            "known50",
            f"known50:{item.index:02d}",
            item.description.strip(),
            target_wikidata_id=item.target_wikidata_id,
            target_film_id=item.target_film_id,
            known=item.known,
        )
        for item in evaluation.load_known50()
    ]


def load_konu30_requests() -> list[EvalRequest]:
    rows = _read_json(_eval_root() / KONU_LISTS, CP1254)
    wanted = {qid for row in rows for qid in row.get("arsivde_bulunan_qidler") or ()}
    in_db = set(Film.objects.filter(wikidata_id__in=wanted).values_list("wikidata_id", flat=True))
    requests = []
    for row in rows:
        text = (row.get("konu_tr") or "").strip()
        qids = frozenset(row.get("arsivde_bulunan_qidler") or ())
        if not text or not qids:
            raise ServiceError(
                f"{row.get('id')}: konu metni ya da cevap listesi boş.", "eval_data_mismatch", 500
            )
        requests.append(
            EvalRequest(
                "konu30",
                f"konu30:{row['id']}",
                text,
                answer_qids=qids,
                answer_in_db=len(qids & in_db),
            )
        )
    return requests


def load_tone25_requests() -> list[EvalRequest]:
    """Cevap anahtarı (kazançlar) `evaluation.load_tone25` ile; metin Türkçe `istek_tr`."""
    items, _ = evaluation.load_tone25()
    turkish = {
        row["id"]: row["istek_tr"]
        for row in _read_json(_eval_root() / evaluation.TONE_REQUESTS, CP1254)
    }
    requests = []
    for item in items:
        text = (turkish.get(item.qid) or "").strip()
        if not text:
            raise ServiceError(f"{item.qid}: Türkçe istek metni yok.", "eval_data_mismatch", 500)
        requests.append(
            EvalRequest(
                "tone25",
                f"tone25:{item.qid}",
                text,
                gains=dict(item.gains),
                relevant=frozenset(item.relevant),
            )
        )
    return requests


LOADERS = {
    "known50": load_known50_requests,
    "konu30": load_konu30_requests,
    "tone25": load_tone25_requests,
}


def sample_requests(requests: list[EvalRequest], sample: int | None) -> list[EvalRequest]:
    """Sabit tohumla karıştırıp ilk N'i alır: aynı N hep aynı istekleri verir (modeller arası
    karşılaştırma için) ve küçük örnek büyüğün içinde kalır. Sıra dosyadaki sıraya döner."""
    ordered = sorted(requests, key=lambda request: request.key)
    if sample is None or sample >= len(ordered):
        return ordered
    positions = list(range(len(ordered)))
    random.Random(f"{SAMPLE_SEED}:{ordered[0].set_name}").shuffle(positions)
    return [ordered[position] for position in sorted(positions[:sample])]


def load_requests(set_names: list[str], sample: int | None) -> list[EvalRequest]:
    requests: list[EvalRequest] = []
    for name in set_names:
        requests += sample_requests(LOADERS[name](), sample)
    return requests
