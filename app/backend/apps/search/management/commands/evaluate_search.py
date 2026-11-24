import json
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core.exceptions import ServiceError
from apps.search.services import evaluation, text, vectors


def _parse_blends(value: str) -> list[float]:
    try:
        blends = [float(part) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        raise CommandError(f"--blend sayılardan oluşmalı: {value}") from exc
    if not blends or any(not 0.0 <= blend <= 1.0 for blend in blends):
        raise CommandError("--blend değerleri 0 ile 1 arasında olmalı.")
    return blends


def _percent(value: float) -> str:
    return f"%{value * 100:.0f}"


class Command(BaseCommand):
    help = (
        "Arama hattını kayıtlı sorgu çözümlemeleriyle ölçer (dil modeli çağrılmaz). "
        "known50: bilinen film testi (R@1/10/50); tone25: ton istekleri (P@10, nDCG@10)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--set", dest="eval_set", required=True, choices=["known50", "tone25"])
        parser.add_argument(
            "--doc",
            default="A,B",
            help="Yeniden sıralama belge kipleri (virgülle): A, B, B_end.",
        )
        parser.add_argument(
            "--blend",
            default="0",
            help="RRF sırasının ağırlığı (virgülle birden çok): 0 = yalnız yeniden sıralama.",
        )
        parser.add_argument("--vector", default="exact", choices=vectors.VECTOR_MODES)
        parser.add_argument(
            "--pool",
            default="none",
            choices=["none", "genome"],
            help="tone25 için aday havuzu: genome = yalnız MovieLens genome kapsamındaki filmler.",
        )
        parser.add_argument(
            "--filters",
            action="store_true",
            help="known50'de modelin çıkardığı filtreleri de uygula (varsayılan: filtresiz).",
        )

    def handle(self, *args, **options):
        docs = [doc.strip() for doc in options["doc"].split(",") if doc.strip()]
        unknown = [doc for doc in docs if doc not in text.DOC_MODES]
        if unknown or not docs:
            raise CommandError(f"--doc şunlardan olmalı: {', '.join(text.DOC_MODES)}")
        blends = _parse_blends(options["blend"])
        started = time.perf_counter()
        try:
            if options["eval_set"] == "known50":
                result = evaluation.run_known50(docs, blends, options["vector"], options["filters"])
                lines = self._known_table(result)
            else:
                result = evaluation.run_tone25(docs, blends, options["vector"], options["pool"])
                lines = self._tone_table(result)
        except ServiceError as exc:
            raise CommandError(f"{exc.message} ({exc.code})") from exc
        result["seconds"] = round(time.perf_counter() - started, 1)
        for line in [*lines, self._timing_line(result)]:
            self.stdout.write(line)
        path = self._write_json(result, docs)
        self.stdout.write(f"JSON: {path}")

    def _write_json(self, result: dict, docs: list[str]) -> Path:
        target = Path(settings.SEARCH["index_dir"]) / "eval"
        target.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = target / f"{result['set']}-{'+'.join(docs)}-{result['vector_mode']}-{stamp}.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        return path

    def _timing_line(self, result: dict) -> str:
        timing = result["gather_seconds"]
        return (
            f"Aday toplama (kip {result['vector_mode']}): ortanca {timing['median']:.3f} sn, "
            f"en uzun {timing['max']:.3f} sn; toplam koşu {result['seconds']} sn"
        )

    def _known_table(self, result: dict) -> list[str]:
        lines = [
            f"known50 (kip {result['vector_mode']}, "
            f"filtre {'var' if result['with_filters'] else 'yok'})",
            "| kol | grup | n | R@1 | R@10 | R@50 |",
            "|---|---|---|---|---|---|",
        ]
        for row in result["rows"]:
            for group, label in (
                ("all", "hepsi"),
                ("known", "bilinen"),
                ("less_known", "az bilinen"),
            ):
                stats = row[group]
                lines.append(
                    f"| {row['arm']} | {label} | {stats['n']} | {_percent(stats['R@1'])} | "
                    f"{_percent(stats['R@10'])} | {_percent(stats['R@50'])} |"
                )
        return lines

    def _tone_table(self, result: dict) -> list[str]:
        lines = [
            f"tone25 (kip {result['vector_mode']}, havuz {result['pool']}, n={result['n']})",
            "| kol | P@10 | nDCG@10 | ortRel@10 | R@50 |",
            "|---|---|---|---|---|",
        ]
        for row in result["rows"]:
            lines.append(
                f"| {row['arm']} | {row['P@10']:.3f} | {row['nDCG@10']:.3f} | "
                f"{row['ortRel@10']:.3f} | {row['R@50']:.3f} |"
            )
        return lines
