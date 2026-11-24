"""Gerçek modelle senaryo turları (kabul ölçümü). `run_scenarios` komutu bunu çağırır.

Turlar çalışan akış ucu üzerinden (`POST /api/chats/{id}/messages/stream`) yürür: aynı
görünüm, kilit, graf ve kayıt kodu. Burada yalnız ölçüm ve rapor vardır.
"""

import time
from dataclasses import asdict, dataclass, field

from asgiref.sync import sync_to_async
from django.conf import settings
from django.test import AsyncClient
from django.test.utils import override_settings

from apps.agent.runtime import get_graph
from apps.agent.services.llm import UsageTally, usage_tally
from apps.agent.streaming import parse_sse
from apps.chats.models import Chat
from apps.chats.services import chats as chat_service
from apps.curation.models import Collection, CollectionFilm
from apps.curation.services.quotes import normalize

# Birim fiyatlar: 1 milyon token başına (girdi, çıktı) dolar. Kaynak: Anthropic fiyat tablosu
# (claude-api becerisindeki 2026-11-03 önbelleği; 100 bin tokenı aşan istemlerde Haiku için
# daha pahalıdır, bu turlarda istemler bunun altındadır).
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
}

SLOW_TURN_SECONDS = 40.0


@dataclass(frozen=True)
class Scenario:
    number: int
    name: str
    text: str
    chat: str  # hangi sohbette: "a" (1. senaryonun sohbeti), "b", "c"
    action: str | None = None  # "replace_first": taslağın ilk filmi


SCENARIOS = [
    Scenario(1, "tema", "Karlı kasabalarda geçen, ağır tempolu polisiyeler", "a"),
    Scenario(2, "ton + dönem", "2015 sonrası, az bilinen, kasvetli psikolojik gerilimler", "b"),
    Scenario(3, "ülke filtreli", "Küçük bir Fransız kasabasında geçen aile komedileri", "c"),
    Scenario(4, "düzeltme (refine)", "Daha karanlık olsun", "a"),
    Scenario(5, "film değiştirme", "Bunun yerine başka bir film bul", "a", "replace_first"),
    Scenario(6, "soru", "{first_title} neden seçildi?", "a"),
]


@dataclass
class TurnReport:
    number: int
    name: str
    text: str
    status: str = "ok"  # ok | error | atlandı
    error: dict | None = None
    seconds: float = 0.0
    step_seconds: dict[str, float] = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    cost_usd: float | None = None
    film_count: int = 0
    filter_violations: int = 0
    quote_match_rate: float | None = None
    dropped_films: int = 0
    notices: list[str] = field(default_factory=list)


def cost_usd(model: str, input_tokens: int, output_tokens: int, prices=None) -> float | None:
    price = (prices or PRICES).get(model)
    if price is None:
        return None
    return (input_tokens * price[0] + output_tokens * price[1]) / 1_000_000


def count_filter_violations(request: dict, films: list[dict]) -> int:
    """Yıl ve ülke filtresini kodla denetler (model değil): kural dışı film sayısı."""
    filters = request.get("filters") or {}
    year_min, year_max = filters.get("year_min"), filters.get("year_max")
    wanted = {name.lower() for name in filters.get("countries") or []}
    violations = 0
    for film in films:
        year = film["year"]
        if year_min is not None and (year is None or year < year_min):
            violations += 1
        elif year_max is not None and (year is None or year > year_max):
            violations += 1
        elif wanted and not wanted & {name.lower() for name in film["countries"]}:
            violations += 1
    return violations


def step_durations(timeline: list[tuple[float, str, dict]]) -> dict[str, float]:
    """`step.start` ile aynı anahtarlı `step.done` arası süreler (yeniden denemeler toplanır)."""
    started: dict[str, float] = {}
    totals: dict[str, float] = {}
    for moment, event, data in timeline:
        if event == "step.start":
            started[data["key"]] = moment
        elif event == "step.done" and data["key"] in started:
            key = data["key"]
            totals[key] = round(totals.get(key, 0.0) + moment - started.pop(key), 2)
    return totals


def quote_match_rate(rows: list[dict]) -> float | None:
    """Kayıtlı alıntıların veritabanındaki kaynak metinde birebir bulunma oranı (beklenen 1.0)."""
    if not rows:
        return None
    found = 0
    for row in rows:
        needle = normalize(row["quote"])
        sources = [row["plot"], row["overview"], *row["reviews"]]
        found += any(needle and needle in normalize(source) for source in sources)
    return round(found / len(rows), 3)


def load_collection_facts(collection_id: int) -> tuple[dict, list[dict], list[dict]]:
    """(istek, film bilgileri, alıntı denetimi için satırlar) — tek sorgu grubu."""
    collection = Collection.objects.get(pk=collection_id)
    rows = list(
        CollectionFilm.objects.filter(collection=collection)
        .select_related("film")
        .prefetch_related("film__reviews")
        .order_by("position")
    )
    films = [{"year": row.film.year, "countries": row.film.countries} for row in rows]
    checks = [
        {
            "quote": row.source_quote,
            "plot": row.film.plot,
            "overview": row.film.overview,
            "reviews": [review.content for review in row.film.reviews.all()],
        }
        for row in rows
    ]
    return collection.request, films, checks


def first_film_of_chat(chat_id: int) -> tuple[int, str] | None:
    collection = Collection.objects.filter(chat_id=chat_id).order_by("-id").first()
    if collection is None:
        return None
    row = (
        CollectionFilm.objects.filter(collection=collection)
        .select_related("film")
        .order_by("position")
        .first()
    )
    return (row.film_id, row.film.title) if row else None


async def run_turn(client: AsyncClient, chat_id: int, text: str, action: dict | None):
    started = time.monotonic()
    body = {"text": text, **({"action": action} if action else {})}
    response = await client.post(
        f"/api/chats/{chat_id}/messages/stream", data=body, content_type="application/json"
    )
    if response.headers["Content-Type"] != "text/event-stream":
        return started, [], response.json()
    timeline = []
    async for chunk in response.streaming_content:
        for event, data in parse_sse(chunk.decode()):
            timeline.append((time.monotonic(), event, data))
    return started, timeline, None


def allow_in_process_host():
    """Süreç içi istemci isteklerini "testserver" adıyla gönderir; bu ad yalnız test koşusunda
    izinlidir. Komut olarak çalışırken yalnız o süreç için izinli hostlara eklenir (yoksa her
    istek DisallowedHost ile düşer). Sunucu sürecinde kullanılmaz."""
    return override_settings(ALLOWED_HOSTS=[*settings.ALLOWED_HOSTS, "testserver"])


async def run_scenarios(
    user, model: str, *, budget_usd: float = 2.0, prices=None, only: set[int] | None = None
) -> dict:
    client = AsyncClient()
    await sync_to_async(client.force_login)(user)
    chats: dict[str, int] = {}
    reports: list[TurnReport] = []
    spent = 0.0
    spend_known = True

    for scenario in SCENARIOS:
        if only and scenario.number not in only:
            continue
        report = TurnReport(scenario.number, scenario.name, scenario.text)
        reports.append(report)
        if spend_known and spent >= budget_usd:
            report.status = "atlandı (harcama sınırı)"
            continue

        if scenario.chat not in chats:
            chat = await sync_to_async(chat_service.create_chat)(user)
            chats[scenario.chat] = chat.pk
        chat_id = chats[scenario.chat]

        text, action = scenario.text, None
        if scenario.action == "replace_first" or "{first_title}" in text:
            first = await sync_to_async(first_film_of_chat)(chat_id)
            if first is None:
                report.status = "atlandı (taslak yok)"
                continue
            if scenario.action == "replace_first":
                action = {"type": "replace_film", "film_id": first[0]}
            text = text.format(first_title=first[1])
            report.text = text

        tally = UsageTally()
        token = usage_tally.set(tally)
        try:
            started, timeline, failure = await run_turn(client, chat_id, text, action)
        finally:
            usage_tally.reset(token)
        report.seconds = round(time.monotonic() - started, 2)
        report.input_tokens, report.output_tokens = tally.input_tokens, tally.output_tokens
        report.calls = tally.calls
        report.cost_usd = cost_usd(model, tally.input_tokens, tally.output_tokens, prices)
        if report.cost_usd is None:
            spend_known = False
        else:
            spent += report.cost_usd
        report.step_seconds = step_durations(timeline)
        report.notices = [data["text"] for _, event, data in timeline if event == "notice"]

        if failure is not None:
            report.status, report.error = "error", failure
            continue
        errors = [data for _, event, data in timeline if event == "error"]
        if errors:
            report.status, report.error = "error", errors[0]
            continue

        collections = [data for _, event, data in timeline if event == "collection"]
        if collections:
            collection = collections[-1]
            report.film_count = len(collection["films"])
            request, films, checks = await sync_to_async(load_collection_facts)(collection["id"])
            report.filter_violations = count_filter_violations(request, films)
            report.quote_match_rate = quote_match_rate(checks)
            thread_id = str((await Chat.objects.aget(pk=chat_id)).thread_id)
            state = await get_graph().aget_state({"configurable": {"thread_id": thread_id}})
            report.dropped_films = int(state.values.get("dropped", 0))

    total_seconds = round(sum(report.seconds for report in reports), 2)
    new_search_seconds = sorted(
        report.seconds for report in reports if report.number in (1, 2, 3) and report.status == "ok"
    )
    median = new_search_seconds[len(new_search_seconds) // 2] if new_search_seconds else None
    return {
        "model": model,
        "budget_usd": budget_usd,
        "spent_usd": round(spent, 4) if spend_known else None,
        "total_seconds": total_seconds,
        "median_new_search_seconds": median,
        "target_new_search_seconds": SLOW_TURN_SECONDS,
        "scenarios": [asdict(report) for report in reports],
    }


def format_summary(result: dict) -> str:
    header = (
        f"{'#':<3}{'senaryo':<20}{'durum':<26}{'sn':>7}{'film':>6}{'ihlal':>7}{'alıntı':>8}"
        f"{'düşen':>7}{'token (g/ç)':>16}{'$':>9}"
    )
    lines = [header, "-" * len(header)]
    for row in result["scenarios"]:
        rate = row["quote_match_rate"]
        cost = row["cost_usd"]
        lines.append(
            f"{row['number']:<3}{row['name']:<20}{row['status']:<26}{row['seconds']:>7.1f}"
            f"{row['film_count']:>6}{row['filter_violations']:>7}"
            f"{('-' if rate is None else f'{rate:.0%}'):>8}{row['dropped_films']:>7}"
            f"{row['input_tokens']:>9}/{row['output_tokens']:<6}"
            f"{('-' if cost is None else f'{cost:.4f}'):>9}"
        )
        if row["step_seconds"]:
            steps = ", ".join(f"{key} {sec:.1f}sn" for key, sec in row["step_seconds"].items())
            lines.append(f"   adımlar: {steps}")
        if row["error"]:
            lines.append(f"   hata: {row['error']}")
    spent = result["spent_usd"]
    lines.append(
        f"Toplam: {result['total_seconds']} sn, harcama: "
        f"{'bilinmiyor' if spent is None else f'${spent}'} (sınır ${result['budget_usd']})"
    )
    median = result["median_new_search_seconds"]
    if median is not None:
        verdict = "hedef içinde" if median < SLOW_TURN_SECONDS else "HEDEFİ AŞIYOR"
        lines.append(f"Yeni arama turları ortanca süre: {median} sn ({verdict}, hedef < 40 sn)")
    return "\n".join(lines)
