"""Uçtan uca ölçüm testleri için ortak yardımcılar: sahte veri dosyaları ve sayaçlı sahte model."""

import asyncio
import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from apps.agent.services.eval_sets import EvalRequest
from apps.agent.services.llm import usage_tally
from apps.agent.tests.base import FakeLLM
from apps.search.services import evaluation

TURKISH = "ğüşiöçıİĞÜŞÖÇ"


def write_json(path: Path, data, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(data, ensure_ascii=False).encode(encoding))


def known_text(n: int) -> str:
    return f"Tarif {n}: karlı kasabada geçen, ağır tempolu bir polisiye {TURKISH}"


def write_known50(root: Path, wikidata_ids: list[str]) -> None:
    """50 hedefli sahte known50 dosyaları (utf-8; kor_tarifler.json de utf-8)."""
    base = root / evaluation.KNOWN_DIR
    targets = [{"id": qid, "tr": known_text(n)} for n, qid in enumerate(wikidata_ids)]
    write_json(base / "b.json", targets[:25])
    write_json(base / "b2.json", targets[25:])
    rows = [
        {
            "kind": "b",
            "n": n,
            "tr": known_text(n),
            "out": {"en_query": "snowy town crime", "hyde": "A detective in the snow."},
        }
        for n in range(50)
    ]
    write_json(base / "haiku_out.json", {"R": rows})
    write_json(base / "kor_tarifler.json", [{"n": n, "tr": known_text(n)} for n in range(50)])


KONU_ROWS = [
    {
        "id": f"konu_{n:02d}",
        "konu_tr": f"karlı kasabalarda geçen {TURKISH} polisiyeler {n}",
        # Q999 veritabanında yok: cevap listesi kapsamı (answer_missing) sınanır.
        "arsivde_bulunan_qidler": ["Q1", "Q2", "Q40"] + (["Q999"] if n == 1 else []),
    }
    for n in range(1, 4)
]


def write_konu30(root: Path) -> None:
    # Gerçek dosya gibi cp1254: Türkçe harfler bu kodlamada tek baytlı.
    write_json(root / "degerlendirme/konu_listeleri.json", KONU_ROWS, encoding="cp1254")


TONE_TEXT = f"kasvetli ve bunaltıcı {TURKISH} filmler"


def write_tone25(root: Path) -> None:
    write_json(
        root / evaluation.TONE_REQUESTS,
        [
            {
                "id": "ton_01",
                "istek_tr": TONE_TEXT,
                "istek_en": "bleak films",
                "etiketler": ["bleak"],
                "ek_kisit": None,
                "uygun_qidler_sayisi": 2,
            }
        ],
        encoding="cp1254",
    )
    write_json(
        root / evaluation.TONE_PARSED,
        [{"id": "ton_01", "out": {"en_query": "bleak", "hyde": "dark", "titles": []}}],
    )
    table = pa.table(
        {
            "QID": ["Q1", "Q2", "Q3"],
            "tag": ["bleak", "bleak", "bleak"],
            "relevance": [0.95, 0.85, 0.1],
        }
    )
    (root / "degerlendirme").mkdir(parents=True, exist_ok=True)
    pq.write_table(table, root / evaluation.GENOME_PARQUET)
    (root / "dataset").mkdir(parents=True, exist_ok=True)
    with open(root / evaluation.DATASET_CSV, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["movie_id", "genre", "country", "year"])
        for qid in ("Q1", "Q2", "Q3"):
            writer.writerow([qid, "drama film", "Finland", "2001"])


def make_eval_request(set_name: str = "konu30", key: str = "a", **fields) -> EvalRequest:
    fields.setdefault("text", f"istek {key}, 5 film")
    return EvalRequest(set_name, f"{set_name}:{key}", **fields)


@dataclass
class MeteredLLM(FakeLLM):
    """Her model çağrısında turun sayacına (bağlam değişkeni) kullanım ekler: gerçek modelin
    `UsageTally` kaydını taklit eder, böylece tur başına token ve harcama ölçümü sınanır."""

    input_tokens: int = 1000
    output_tokens: int = 500
    # Metni şu parçayı içeren turun çağrıları bu katla sayılır: turlar karışırsa token tutmaz.
    weights: dict = field(default_factory=dict)
    # Verilirse her turun `parse` adımı bu bariyerde bekler: bariyer ancak turlar GERÇEKTEN
    # aynı anda uçuştaysa açılır (seri koşarsa zaman aşımıyla hata verir).
    barrier: asyncio.Barrier | None = None

    def meter(self, step: str, user: str) -> None:
        tally = usage_tally.get()
        if tally is None:
            return
        weight = next((w for part, w in self.weights.items() if part in user), 1)
        tally.add(step, self.input_tokens * weight, self.output_tokens * weight, 0.0)

    async def structured(self, **kwargs):
        if self.barrier is not None and kwargs["step"] == "parse":
            async with asyncio.timeout(5):
                await self.barrier.wait()
        result = await super().structured(**kwargs)
        self.meter(kwargs["step"], kwargs["user"])
        return result

    async def stream_text(self, **kwargs):
        async for piece in super().stream_text(**kwargs):
            yield piece
        self.meter(kwargs["step"], kwargs["user"])
