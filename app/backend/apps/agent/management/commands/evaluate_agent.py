import asyncio
import time
from pathlib import Path

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from apps.agent import scenarios
from apps.agent.runtime import open_runtime
from apps.agent.services import eval_run, eval_sets
from apps.agent.services.llm import AnthropicLLM
from apps.agent.services.retrieval import SearchServiceRetrieval
from apps.core.exceptions import ServiceError


def build_llm(model: str):
    """Yalnız bu koşu için model; ayar (`ANTHROPIC_MODEL`) değişmez. Testler sahtesini verir."""
    return AnthropicLLM(model=model)


def build_retrieval():
    return SearchServiceRetrieval()


class Command(BaseCommand):
    help = (
        "Editörün Türkçe isteğinden taslağa kadar bütün hattı (canlı çözümleme, arama, "
        "değerlendirme, yazım, alıntı doğrulama) üç cevap anahtarına karşı ölçer. GERÇEK modelle "
        "para harcar: --budget ile sınırla. Onaylama yapılmaz."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--set",
            dest="sets",
            action="append",
            required=True,
            choices=eval_sets.SET_NAMES,
            help="known50 | konu30 | tone25 (birden çok kez verilebilir)",
        )
        parser.add_argument("--model", help="Yalnız bu koşu için model adı (varsayılan: ayardaki)")
        parser.add_argument(
            "--sample", type=int, help="Her kümeden sabit tohumla seçilmiş N istek (modeller aynı)"
        )
        parser.add_argument("--concurrency", type=int, default=2, help="Aynı anda en çok K tur")
        parser.add_argument(
            "--budget",
            type=float,
            help=(
                f"Toplam harcama sınırı (dolar; verilmezse ${eval_run.DEFAULT_BUDGET_USD:g}). "
                "Devam eden dosyada önceki harcama da sayılır."
            ),
        )
        parser.add_argument(
            "--no-budget",
            action="store_true",
            help="Harcama sınırı olmadan koş (fiyatı bilinmeyen modelde zorunlu).",
        )
        parser.add_argument("--out", help="JSON çıktı yolu (aynı yol verilirse koşu devam eder)")
        parser.add_argument(
            "--keep", action="store_true", help="Koşuda açılan sohbet ve koleksiyonları silme"
        )

    def handle(self, *args, **options):
        model = options["model"] or settings.ANTHROPIC_MODEL
        sets = list(dict.fromkeys(options["sets"]))
        for name, minimum in (("sample", 1), ("concurrency", 1)):
            if options[name] is not None and options[name] < minimum:
                raise CommandError(f"--{name} en az {minimum} olmalı.")
        if options["budget"] is not None and options["budget"] <= 0:
            raise CommandError("--budget sıfırdan büyük olmalı.")

        # Fiyatı bilinmeyen modelde harcama sınırı denetlenemez; sınırsız koşu yalnız açık
        # --no-budget ile başlar (sessizce sınırsız para harcanmasın).
        price_known = model in scenarios.PRICES
        if options["no_budget"] and options["budget"] is not None:
            raise CommandError("--budget ile --no-budget birlikte verilemez.")
        if not price_known:
            if options["budget"] is not None:
                raise CommandError(
                    f"{model} için fiyat bilinmiyor; harcama sınırı denetlenemez. "
                    "--budget kullanılamaz; sınırsız koşmak için --no-budget ver."
                )
            if not options["no_budget"]:
                raise CommandError(
                    f"{model} için fiyat bilinmiyor, harcama sınırı uygulanamaz. Parayı kendin "
                    "izleyeceksen açıkça --no-budget ver; harcama 'bilinmiyor' yazılır."
                )
            self.stderr.write(f"UYARI: {model} için fiyat bilinmiyor; harcama sınırı uygulanmıyor.")
        budget = None if options["no_budget"] else options["budget"]
        if budget is None and price_known and not options["no_budget"]:
            budget = eval_run.DEFAULT_BUDGET_USD

        try:
            requests = eval_sets.load_requests(sets, options["sample"])
            user = eval_run.get_eval_user()
            out_path = self.out_path(options["out"], sets, model)
            with scenarios.allow_in_process_host():
                report = asyncio.run(
                    self.run(user, requests, model, sets, out_path, budget, options)
                )
        except ServiceError as exc:
            raise CommandError(f"{exc.message} ({exc.code})") from exc
        self.stdout.write(eval_run.format_summary(report))
        self.stdout.write(f"JSON: {out_path}")

    def out_path(self, given: str | None, sets: list[str], model: str) -> Path:
        if given:
            return Path(given)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        directory = Path(settings.SEARCH["index_dir"]) / "eval" / "agent"
        return directory / f"{'+'.join(sets)}-{model}-{stamp}.json"

    async def run(self, user, requests, model, sets, out_path, budget, options):
        retrieval = eval_run.RecordingRetrieval(build_retrieval())
        try:
            async with open_runtime(llm=build_llm(model), retrieval=retrieval):
                return await eval_run.run_evaluation(
                    user,
                    requests,
                    model=model,
                    sets=sets,
                    out_path=out_path,
                    prices=scenarios.PRICES,
                    budget_usd=budget,
                    concurrency=options["concurrency"],
                    sample=options["sample"],
                    keep=options["keep"],
                )
        finally:
            # sync_to_async iş parçacığının açtığı veritabanı bağlantıları olay döngüsüyle ölmez.
            await sync_to_async(connections.close_all)()
