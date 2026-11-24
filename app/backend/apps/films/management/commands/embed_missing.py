from django.core.management.base import BaseCommand, CommandError

from apps.core.exceptions import ServiceError
from apps.films.services import embedding


class Command(BaseCommand):
    help = "Parçası/kart vektörü olmayan filmleri bge-m3 ile vektöre çevirir (ekran kartı gerekir)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=embedding.DEFAULT_BATCH_SIZE,
            help="Ekran kartı belleği yetmezse küçültün.",
        )

    def handle(self, *args, **options):
        try:
            summary = embedding.embed_missing(
                embedder=embedding.make_embedder(options["batch_size"])
            )
        except ServiceError as exc:
            raise CommandError(f"{exc.message} ({exc.code})") from exc
        self.stdout.write(summary.describe())
        self.stdout.write(f"Süreler (sn): {summary.seconds}")
