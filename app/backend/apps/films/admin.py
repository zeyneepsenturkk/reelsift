from django.contrib import admin

from apps.films.models import Film, FilmChunk, FilmProfile, FilmReview


class ReadOnlyAdmin(admin.ModelAdmin):
    """Veri yüklemeyle gelir; yönetim panelinde yalnız görüntülenir."""

    show_full_result_count = False

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Film)
class FilmAdmin(ReadOnlyAdmin):
    list_display = ("title", "year", "tmdb_id", "vote_count", "plot_source")
    list_filter = ("plot_source",)
    search_fields = ("title", "original_title", "tr_title", "wikidata_id", "imdb_id")
    exclude = ("card_embedding",)


@admin.register(FilmChunk)
class FilmChunkAdmin(ReadOnlyAdmin):
    # Liste her satırda film adını gösterdiği için film tek sorguda birleştirilir.
    list_display = ("film", "position")
    list_select_related = ("film",)
    raw_id_fields = ("film",)
    search_fields = ("film__title",)
    exclude = ("embedding",)


@admin.register(FilmProfile)
class FilmProfileAdmin(ReadOnlyAdmin):
    list_display = ("film", "pacing", "evidence")
    # Liste her satırda film adını gösterir; N+1 olmasın diye film tek sorguda birleştirilir.
    list_select_related = ("film",)
    list_filter = ("pacing", "evidence")
    raw_id_fields = ("film",)
    search_fields = ("film__title", "tr_pitch")


@admin.register(FilmReview)
class FilmReviewAdmin(ReadOnlyAdmin):
    list_display = ("film", "rating", "published_at")
    # Liste her satırda film adını gösterir; N+1 olmasın diye film tek sorguda birleştirilir.
    list_select_related = ("film",)
    raw_id_fields = ("film",)
    search_fields = ("film__title", "content")
