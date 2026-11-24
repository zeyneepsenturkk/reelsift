from django.core.management.base import BaseCommand

from apps.search.services import lexical


class Command(BaseCommand):
    help = "Kelime araması (BM25) ve ad eşleme indeksini veritabanındaki metinlerden yeniden kurar."

    def handle(self, *args, **options):
        summary = lexical.build_index()
        self.stdout.write(
            f"İndeks kuruldu: {summary['film_count']} film, süreler (sn): {summary['seconds']}, "
            f"yol: {lexical.index_path()}"
        )
