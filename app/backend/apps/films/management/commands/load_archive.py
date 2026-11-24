from django.core.management.base import BaseCommand, CommandError

from apps.core.exceptions import ServiceError
from apps.films.services import loading


class Command(BaseCommand):
    help = (
        "Film arşivini /data altından veritabanına yükler (tekrar çalıştırılabilir). "
        "Metni ve içeriği değişmemiş film/parça yeniden yazılmaz; vektör dosyası AYNI metinle "
        "değişirse ilgili parçalar önce silinmelidir. Büyük yüklemede HNSW indeksleri geçici "
        "düşürülüp sonunda yeniden kurulur."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Yalnız veri setinin ilk N filmini (ve onlara bağlı kayıtları) yükler.",
        )

    def handle(self, *args, **options):
        try:
            summary = loading.load_archive(limit=options["limit"])
        except ServiceError as exc:
            raise CommandError(f"{exc.message} ({exc.code})") from exc
        self.stdout.write(summary.describe())
        self.stdout.write(f"Süreler (sn): {summary.seconds}")
