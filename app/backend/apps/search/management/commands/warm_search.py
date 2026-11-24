from django.core.management.base import BaseCommand

from apps.search.services import warmup


class Command(BaseCommand):
    help = (
        "Arama modellerini ve kelime indeksini yükler, bir kukla arama çalıştırır "
        "(Postgres önbelleği de ısınır); adım sürelerini yazar."
    )

    def handle(self, *args, **options):
        for step, seconds in warmup.warm_search().items():
            self.stdout.write(f"{step}: {seconds} sn")
