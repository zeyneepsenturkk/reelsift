import asyncio
import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.agent import scenarios
from apps.agent.runtime import open_runtime

DEFAULT_OUTPUT = "/index/eval/senaryolar.json"


class Command(BaseCommand):
    help = (
        "6 senaryo turunu GERÇEK modelle, çalışan akış ucu üzerinden koşar ve rapor yazar "
        "(süre, token, maliyet, film sayısı, filtre ihlali, alıntı doğruluğu, düşen film)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--username", default="gelistirme", help="Geliştirme kullanıcısı")
        parser.add_argument("--budget", type=float, default=2.0, help="Harcama sınırı (dolar)")
        parser.add_argument("--output", default=DEFAULT_OUTPUT, help="JSON rapor yolu")
        parser.add_argument("--only", type=int, nargs="*", help="Yalnız bu senaryo numaraları")
        parser.add_argument("--input-price", type=float, help="Modelin 1M girdi token fiyatı ($)")
        parser.add_argument("--output-price", type=float, help="Modelin 1M çıktı token fiyatı ($)")

    def handle(self, *args, **options):
        model = settings.ANTHROPIC_MODEL
        prices = dict(scenarios.PRICES)
        if options["input_price"] is not None and options["output_price"] is not None:
            prices[model] = (options["input_price"], options["output_price"])
        if model not in prices:
            raise CommandError(
                f"{model} için fiyat bilinmiyor; --input-price ve --output-price ver "
                "(harcama sınırı fiyat olmadan denetlenemez)."
            )
        user_model = get_user_model()
        user, created = user_model.objects.get_or_create(username=options["username"])
        if created:
            user.set_unusable_password()
            user.save(update_fields=["password"])

        with scenarios.allow_in_process_host():
            result = asyncio.run(self.run(user, model, options, prices))
        self.stdout.write(scenarios.format_summary(result))
        self.write_report(result, Path(options["output"]))

    async def run(self, user, model, options, prices):
        async with open_runtime():
            return await scenarios.run_scenarios(
                user,
                model,
                budget_usd=options["budget"],
                prices=prices,
                only=set(options["only"]) if options["only"] else None,
            )

    def write_report(self, result: dict, path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            self.stderr.write(f"Rapor dosyası yazılamadı ({path}): {exc.strerror}")
            return
        self.stdout.write(f"Rapor: {path}")
