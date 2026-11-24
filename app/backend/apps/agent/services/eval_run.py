"""Uçtan uca ölçüm koşusu: istek başına yeni sohbet, çalışan akış ucu, ölçüm kaydı, devam, temizlik.

Her tur `run_scenarios` ile aynı yoldan yürür (`POST /api/chats/{id}/messages/stream`, süreç içi
istemci). Aramanın aday listesi graf durumundan okunamaz (tur sonunda temizlenir); bu yüzden arama
servisi sınırında ince bir kaydedici vardır ve hangi tura ait olduğu bağlam değişkeniyle bulunur.
Onaylama yapılmaz: `approve_collection` bu modülden çağrılmaz.
"""

import asyncio
import contextvars
import json
import logging
import os
import time
from collections.abc import Collection as CollectionType
from dataclasses import dataclass, field
from pathlib import Path

from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.test import AsyncClient

from apps.agent import scenarios
from apps.agent.runtime import get_graph
from apps.agent.services import eval_metrics
from apps.agent.services.eval_sets import EvalRequest
from apps.agent.services.llm import UsageTally, usage_tally
from apps.chats.models import Chat
from apps.chats.services import chats as chat_service
from apps.core.exceptions import ServiceError
from apps.curation.models import Collection, CollectionFilm

logger = logging.getLogger(__name__)

EVAL_USERNAME = "eval_runner"
DEFAULT_BUDGET_USD = 3.0
REPORT_VERSION = 2
FINISHED = (eval_metrics.STATUS_OK, eval_metrics.STATUS_NO_DRAFT)

DEFINITIONS = {
    "genel": (
        "Her ölçüt iki oranla verilir ve her oranın yanında KENDİ paydası (n) yazılır. "
        "`_defined`: ölçütün tanımlı olduğu turlar üzerinden. `_all`: bütün istekler (n_total) "
        "üzerinden; modelin hata verdiği tur ve taslağı çıkmayan tur 0 (ıska) sayılır. "
        "n_total = istek sayısı; n_ok = hatasız biten tur sayısı (ok + taslak yok)."
    ),
    "hit_draft": (
        "hit_draft = hedef filmi taslakta olan tur sayısı / payda. _defined: payda n_ok "
        "(hatasız biten turlar; 'taslak yok' turu ıska sayılır, hatalı tur dışarıda). "
        "_all: payda n_total (hatalı tur da ıska)."
    ),
    "R@k": (
        "R@k = hedef filmi aramanın turdaki ilk çağrısının ilk k adayında olan tur sayısı / "
        "payda. _defined: payda n_searched (arama yapılmış hatasız turlar; hatalı ve aramasız "
        "tur dışarıda). _all: payda n_total (hatalı ve aramasız tur ıska)."
    ),
    "precision_draft": (
        "precision_draft = turlarda (taslaktaki filmlerden cevap listesinde olanlar / taslaktaki "
        "film sayısı) değerinin ortalaması; ALT SINIRDIR. _defined: payda n_with_draft (taslağı "
        "çıkan hatasız turlar; hatalı ve taslaksız tur dışarıda). _all: payda n_total (hatalı "
        "ve taslaksız tur 0)."
    ),
    "precision_covered": (
        "precision_covered = turlarda (genome kapsamındaki taslak filmlerden uygun olanlar / "
        "kapsamdaki film sayısı) değerinin ortalaması; tur içindeki kapsam dışı filmler pay ve "
        "paydaya girmez (ayrıca sayılır). _defined: payda n_with_coverage (taslağında en az bir "
        "kapsamdaki film olan turlar). _all: payda n_total - n_unjudgeable; hatalı ve taslaksız "
        "tur (filmi olmayan taslak dahil) 0 sayılır. n_unjudgeable = taslağında en az bir film "
        "olup hiçbiri genome kapsamında olmayan tur: "
        "veri sınırıdır, model hatası değil; payda dışıdır ve 'yargılanamadı (genome kapsamı "
        "dışı)' diye ayrı sayılır."
    ),
}
SET_DEFINITIONS = {
    "known50": ("hit_draft", "R@k"),
    "konu30": ("precision_draft",),
    "tone25": ("precision_covered",),
}

BUDGET_NOTE = (
    "Harcama sınırı tur BAŞLAMADAN denetlenir: sınır aşımı en çok eşzamanlılık x tek tur maliyeti "
    "kadar olabilir (uçuştaki turlar biter). Yeniden denenen hatalı turun eski denemelerinin "
    "harcaması da toplama dahildir."
)

NOTES = {
    "known50": (
        "İstek metni kayıtlı Türkçe tariftir (olduğu gibi). hit_draft: hedef film taslakta mı. "
        "R@k: aramanın turdaki İLK çağrısının aday listesinden, canlı çözümlemeyle (filtreler "
        "dahil; evaluate_search ise kayıtlı çözümleme ve filtresiz ölçer, sayılar eşit değildir)."
    ),
    "konu30": (
        "precision_draft ALT SINIRDIR: cevap listesi (Wikipedia listesinin arşivde bulunan kısmı) "
        "eksik olabilir; listede olmayan ama konuya uyan film yanlış sayılır. Kesinlik payı "
        "taslaktaki film sayısıdır: cevap listesinde olup veritabanında karşılığı olmayan "
        "kimlikler paydaya girmez (sayıları answer_key / özet: answer_missing)."
    ),
    "tone25": (
        "Yalnız genome kapsamındaki filmler yargılanır (uygun: etiket uygunluğu >= eşik ve ek "
        "kısıt sağlanır). Kapsam dışı filmler 'uncovered' diye ayrı sayılır, kesinliğe girmez."
    ),
}


@dataclass
class SearchCall:
    film_ids: tuple[int, ...]
    relaxed: tuple[str, ...]
    seconds: float


search_log: contextvars.ContextVar[list[SearchCall] | None] = contextvars.ContextVar(
    "agent_eval_search_log", default=None
)


class RecordingRetrieval:
    """Arama servisini sarar; çağrının adaylarını o anki turun kaydına ekler, sonucu değiştirmez."""

    def __init__(self, inner):
        self.inner = inner

    async def search(self, request, *, limit, exclude_film_ids=()):
        started = time.monotonic()
        result = await self.inner.search(request, limit=limit, exclude_film_ids=exclude_film_ids)
        log = search_log.get()
        if log is not None:
            log.append(
                SearchCall(
                    tuple(candidate.film_id for candidate in result.candidates),
                    tuple(result.relaxed_filters),
                    round(time.monotonic() - started, 2),
                )
            )
        return result


def get_eval_user():
    """Ölçüm kullanıcısı: her koşuda şifresi kullanılamaz yapılır; yönetici yetkisi varsa durur
    (kullanıcı önceden başka biçimde açılmış olabilir)."""
    user, _ = get_user_model().objects.get_or_create(username=EVAL_USERNAME)
    if user.is_staff or user.is_superuser:
        raise ServiceError(
            f"{EVAL_USERNAME} kullanıcısı yönetici yetkili (is_staff/is_superuser); ölçüm "
            "durduruldu. Yetkiyi kaldır ya da kullanıcıyı sil.",
            "eval_user_privileged",
            500,
        )
    if user.has_usable_password():
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user


@dataclass
class RunState:
    """Koşunun ortak durumu (tek olay döngüsünde, bekleme noktaları arasında güvenli)."""

    spent: float
    spend_known: bool
    budget_usd: float | None
    records: dict[str, dict]
    created_chats: list[tuple[int, str]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def over_budget(self) -> bool:
        return self.budget_usd is not None and self.spend_known and self.spent >= self.budget_usd


def load_draft(collection_id: int) -> tuple[list[dict], list[dict]]:
    """(taslaktaki filmler sırayla, alıntı denetimi satırları)."""
    _, _, checks = scenarios.load_collection_facts(collection_id)
    rows = (
        CollectionFilm.objects.filter(collection_id=collection_id)
        .select_related("film")  # kimlik ve ad için film tek sorguda
        .order_by("position")
    )
    draft = [
        {"film_id": row.film_id, "wikidata_id": row.film.wikidata_id, "title": row.film.title}
        for row in rows
    ]
    return draft, checks


def set_metrics(request: EvalRequest, draft: list[dict], search_calls: list[SearchCall]) -> dict:
    film_ids = [film["film_id"] for film in draft]
    if request.set_name == "known50":
        metrics = eval_metrics.known_metrics(
            request.target_film_id, film_ids, [call.film_ids for call in search_calls]
        )
        return metrics | {"target": request.target_wikidata_id, "known": request.known}
    if request.set_name == "konu30":
        qids = [film["wikidata_id"] for film in draft]
        matched = sum(1 for qid in qids if qid in request.answer_qids)
        return {
            "answer_size": len(request.answer_qids),
            "matched": matched,
            "precision_draft": eval_metrics.precision_draft(qids, request.answer_qids),
        }
    return eval_metrics.tone_metrics(film_ids, request.gains, request.relevant) | {
        "relevant_total": len(request.relevant)
    }


def empty_record(request: EvalRequest) -> dict:
    return {
        "key": request.key,
        "set": request.set_name,
        "text": request.text,
        "status": eval_metrics.STATUS_OK,
        "error": None,
        "chat_id": None,
        "seconds": 0.0,
        "step_seconds": {},
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": None,  # bu denemenin harcaması
        "attempts": 1,
        "total_cost_usd": None,  # bütün denemelerin toplamı (yeniden denemede eskiler dahil)
        "film_count": 0,
        "quote_match_rate": None,
        "dropped_films": 0,
        "relaxed_by_agent": [],
        "relaxed_by_search": [],
        "search_calls": 0,
        "draft": [],
        "metrics": {},
        "answer_key": answer_key_of(request),
    }


def answer_key_of(request: EvalRequest) -> dict | None:
    """konu30'da cevap listesinin veritabanı kapsamı (turun başarısından bağımsız)."""
    if request.set_name != "konu30" or request.answer_in_db is None:
        return None
    size = len(request.answer_qids)
    return {"size": size, "in_db": request.answer_in_db, "missing": size - request.answer_in_db}


async def measure_request(request: EvalRequest, user, model: str, prices, state: RunState) -> dict:
    """Bir isteği ölçer. Beklenmeyen hata koşuyu durdurmaz: istek "hata" olarak kaydedilir ve o
    ana kadar harcanan token ve para yine kayda geçer."""
    record = empty_record(request)
    tally, calls = UsageTally(), []
    try:
        await _measure_turn(request, user, record, tally, calls, state)
    except Exception as exc:  # tek isteğin hatası uçuştaki diğer turları iptal etmesin
        logger.exception("Ölçüm turu beklenmedik hatayla bitti: %s", request.key)
        record["status"] = eval_metrics.STATUS_ERROR
        record["error"] = {
            "detail": f"Ölçüm sırasında beklenmeyen hata: {type(exc).__name__}",
            "code": "eval_exception",
        }
    record["input_tokens"], record["output_tokens"] = tally.input_tokens, tally.output_tokens
    record["calls"] = tally.calls
    record["cost_usd"] = scenarios.cost_usd(model, tally.input_tokens, tally.output_tokens, prices)
    record["total_cost_usd"] = record["cost_usd"]
    record["search_calls"] = len(calls)
    return record


async def _measure_turn(request, user, record, tally, calls, state) -> None:
    chat = await sync_to_async(chat_service.create_chat)(user)
    state.created_chats.append((chat.pk, str(chat.thread_id)))
    record["chat_id"] = chat.pk

    client = AsyncClient()
    await sync_to_async(client.force_login)(user)
    tally_token, log_token = usage_tally.set(tally), search_log.set(calls)
    try:
        started, timeline, failure = await scenarios.run_turn(client, chat.pk, request.text, None)
    finally:
        usage_tally.reset(tally_token)
        search_log.reset(log_token)

    record["seconds"] = round(time.monotonic() - started, 2)
    record["step_seconds"] = scenarios.step_durations(timeline)

    errors = [data for _, event, data in timeline if event == "error"]
    if failure is not None or errors:
        record["status"], record["error"] = eval_metrics.STATUS_ERROR, failure or errors[0]
        return

    snapshot = await get_graph().aget_state({"configurable": {"thread_id": str(chat.thread_id)}})
    record["dropped_films"] = int(snapshot.values.get("dropped", 0))
    record["relaxed_by_agent"] = list(snapshot.values.get("applied_relax", []))
    record["relaxed_by_search"] = list(
        dict.fromkeys(name for call in calls for name in call.relaxed)
    )

    collections = [data for _, event, data in timeline if event == "collection"]
    draft, checks = [], []
    if collections:
        draft, checks = await sync_to_async(load_draft)(collections[-1]["id"])
    else:
        record["status"] = eval_metrics.STATUS_NO_DRAFT
    record["draft"] = draft
    record["film_count"] = len(draft)
    record["quote_match_rate"] = scenarios.quote_match_rate(checks)
    record["metrics"] = set_metrics(request, draft, calls)


def header_of(model: str, sets: list[str], sample: int | None) -> dict:
    return {"version": REPORT_VERSION, "model": model, "sets": sets, "sample": sample}


def load_previous(path: Path, header: dict) -> dict:
    """Aynı çıktı dosyası varsa kayıtları döner; başka model/küme/örnekle üretilmişse reddeder."""
    if not path.exists():
        return {}
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ServiceError(
            f"Önceki çıktı okunamadı: {path}", "eval_resume_unreadable", 500
        ) from exc
    if previous.get("version") != REPORT_VERSION:
        raise ServiceError(
            f"{path}: uyumsuz çıktı sürümü (dosya {previous.get('version')}, beklenen "
            f"{REPORT_VERSION}); oran tanımları değiştiği için devam edilemez. Farklı bir "
            "--out ver.",
            "eval_resume_incompatible",
            400,
        )
    if any(previous.get(name) != value for name, value in header.items()):
        raise ServiceError(
            f"{path} başka bir koşuya ait (model/küme/örnek farklı); devam edilemez. "
            "Farklı bir --out ver.",
            "eval_resume_mismatch",
            400,
        )
    return previous.get("requests", {})


def build_report(header: dict, state: RunState, extra: dict) -> dict:
    by_set = {name: [] for name in header["sets"]}
    for record in state.records.values():
        by_set[record["set"]].append(record)
    return {
        **header,
        **extra,
        "spent_usd": round(state.spent, 4) if state.spend_known else None,
        "stopped_at_budget": bool(state.skipped),
        "skipped": list(state.skipped),
        "definitions": DEFINITIONS,
        "budget_note": BUDGET_NOTE,
        "notes": {name: NOTES[name] for name in header["sets"]},
        "summary": {
            name: eval_metrics.summarize_set(name, records) for name, records in by_set.items()
        },
        "requests": state.records,
    }


def write_report(path: Path, report: dict) -> None:
    """Önce geçici dosyaya, sonra yer değiştirme: yarıda kesilirse eski tam dosya kalır."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temporary, path)


def delete_run_data(user, chat_ids: list[int]) -> None:
    """Yalnız bu koşuda açılan sohbetler ve bunlara bağlı, bu kullanıcının koleksiyonları.
    Koleksiyon sohbet silinince kalır (SET_NULL), bu yüzden önce o silinir."""
    Collection.objects.filter(owner=user, chat_id__in=chat_ids).delete()
    Chat.objects.filter(user=user, pk__in=chat_ids).delete()


async def cleanup(user, created: CollectionType[tuple[int, str]]) -> None:
    chat_ids = [chat_id for chat_id, _ in created]
    await sync_to_async(delete_run_data)(user, chat_ids)
    checkpointer = getattr(get_graph(), "checkpointer", None)
    if checkpointer is None:
        return
    for _, thread_id in created:
        await checkpointer.adelete_thread(thread_id)


async def run_evaluation(
    user,
    requests: list[EvalRequest],
    *,
    model: str,
    sets: list[str],
    out_path: Path,
    prices=None,
    budget_usd: float | None = None,
    concurrency: int = 2,
    sample: int | None = None,
    keep: bool = False,
) -> dict:
    header = header_of(model, sets, sample)
    previous = await sync_to_async(load_previous)(out_path, header)
    state = RunState(
        spent=sum(record["total_cost_usd"] or 0.0 for record in previous.values()),
        spend_known=all(record["total_cost_usd"] is not None for record in previous.values()),
        budget_usd=budget_usd,
        records=dict(previous),
    )
    # Hatalı turlar yeniden denenir; bitmiş (ok / taslak yok) turlar atlanır.
    pending = [
        request
        for request in requests
        if state.records.get(request.key, {}).get("status") not in FINISHED
    ]
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    extra = {
        "concurrency": concurrency,
        "budget_usd": budget_usd,
        "started_at": started_at,
        "resumed_from": len(previous),
    }
    semaphore = asyncio.Semaphore(concurrency)

    async def run_one(request: EvalRequest) -> None:
        async with semaphore:
            if state.over_budget():
                state.skipped.append(request.key)
                return
            record = await measure_request(request, user, model, prices, state)
        earlier = state.records.get(request.key)
        if earlier is not None:
            # Yeniden deneme: eski denemelerin harcaması kayıttan ve toplamdan düşmez.
            record["attempts"] = earlier["attempts"] + 1
            if earlier["total_cost_usd"] is None or record["cost_usd"] is None:
                record["total_cost_usd"] = None
            else:
                record["total_cost_usd"] = round(earlier["total_cost_usd"] + record["cost_usd"], 6)
        if record["cost_usd"] is None:
            state.spend_known = False
        else:
            state.spent += record["cost_usd"]  # eski denemeler `spent`e zaten girmişti
        state.records[request.key] = record
        write_report(out_path, build_report(header, state, extra))

    started = time.monotonic()
    try:
        async with asyncio.TaskGroup() as group:
            for request in pending:
                group.create_task(run_one(request))
    finally:
        if not keep:
            await cleanup(user, state.created_chats)
    extra["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    extra["run_seconds"] = round(time.monotonic() - started, 1)
    report = build_report(header, state, extra)
    write_report(out_path, report)
    return report


def _percent(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def _dollars(value: float | None) -> str:
    return "bilinmiyor" if value is None else f"${value}"


def format_summary(report: dict) -> str:
    lines = [
        f"Model: {report['model']}, örnek: {report['sample'] or 'tümü'}, "
        f"eşzamanlılık: {report['concurrency']}",
        f"Tanım: {report['definitions']['genel']}",
    ]
    for name, row in report["summary"].items():
        lines.append("")
        lines.append(
            f"[{name}] n_total={row['n_total']}, n_ok={row['n_ok']} (ok {row['ok']}, "
            f"taslak yok {row['no_draft']}), hata {row['failed']}, deneme {row['attempts']}"
        )
        lines.append(
            f"  ort. film {row['mean_films']}, alıntı eşleşme {_percent(row['mean_quote_match'])}, "
            f"ort. düşen {row['mean_dropped']}, ort. model çağrısı {row['mean_calls']}"
        )
        lines.append(
            f"  süre ortanca {row['seconds_median']} sn, en uzun {row['seconds_max']} sn; "
            f"harcama {_dollars(row['total_cost_usd'])} "
            f"(istek başına {_dollars(row['mean_cost_usd'])})"
        )
        lines += [f"  {line}" for line in _set_lines(name, row)]
        lines += [f"  tanım {key}: {report['definitions'][key]}" for key in SET_DEFINITIONS[name]]
        lines.append(f"  not: {report['notes'][name]}")
    lines.append("")
    lines.append(f"Toplam harcama: {_dollars(report['spent_usd'])}")
    if report["budget_usd"] is not None:
        lines.append(f"Sınır ${report['budget_usd']}. {report['budget_note']}")
    if report["stopped_at_budget"]:
        lines.append(
            f"SINIRDA DURDU (${report['budget_usd']}): {len(report['skipped'])} istek başlatılmadı."
        )
    return "\n".join(lines)


def _rate_text(value: dict) -> str:
    return f"{_percent(value['value'])} (n={value['n']}, payda {value['denominator']})"


def _pair(row: dict, name: str) -> str:
    """İki değerli ölçüt: `_defined` (tanımlı turlar) ve `_all` (bütün istekler)."""
    return (
        f"{name}: tanımlı turlarda {_rate_text(row[name + '_defined'])} | "
        f"bütün isteklerde {_rate_text(row[name + '_all'])}"
    )


def _set_lines(name: str, row: dict) -> list[str]:
    if name == "known50":
        lines = [_pair(row, "hit_draft") + f"; ort. sıra {row['mean_draft_rank']}"]
        return lines + [_pair(row, f"R@{k}") for k in (1, 10, 50)]
    if name == "konu30":
        return [
            _pair(row, "precision_draft") + " (alt sınır)",
            f"cevap listeleri: {row['answer_ids']} kimlik, veritabanında {row['answer_in_db']}, "
            f"karşılığı olmayan {row['answer_missing']} (kesinlik paydasında yok)",
        ]
    return [
        _pair(row, "precision_covered"),
        f"yargılanamadı (genome kapsamı dışı): {row['n_unjudgeable']} tur; "
        f"kapsamda {row['covered']} film, kapsam dışı {row['uncovered']}",
    ]
