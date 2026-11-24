"""Agent akışı (LangGraph iskeleti; adımların içinde doğrudan Anthropic SDK'sı).

Taslağın tek doğruluk kaynağı VERİTABANIDIR. Graf durumu yalnız çözümlenmiş isteği, aday
kimliklerini, sayaçları ve koleksiyon kimliğini taşır; yazılmış ama henüz doğrulanmamış film
metinleri (`pending`) yalnız `write` -> `verify` -> `persist` arasında geçicidir ve turun
sonunda temizlenir.

Onay: bu modül `approve_collection`'ı İÇE AKTARMAZ; grafta onaya giden hiçbir yol yoktur.
"""

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, TypedDict

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import transaction
from langgraph.config import get_stream_writer
from langgraph.graph import START, StateGraph
from langgraph.types import interrupt
from pydantic import ValidationError

from apps.agent import prompts
from apps.agent.schemas import (
    MAX_TARGET,
    MIN_TARGET,
    AltQueryOutput,
    FilmWriting,
    FiltersLM,
    JudgeOutput,
    ParsedRequest,
    PersonHint,
    PersonLM,
    RequestLM,
    SelectOutput,
    TitleHintLM,
    UnderstandOutput,
    WriteOutput,
    clean_people,
    sanitize_request,
)
from apps.agent.services import data, language, relax, texts
from apps.agent.services.llm import MSG_BAD_OUTPUT, LLMError, LLMRefused
from apps.agent.services.verification import verify_writings
from apps.chats.models import Chat
from apps.chats.services import chats as chat_service
from apps.curation.services.drafts import KeptFilm, NewFilm
from apps.curation.services.genres import genre_name_tr
from apps.search.services.people import normalize_person

logger = logging.getLogger(__name__)

SEARCH_INTENTS = ("new_search", "refine", "replace_film")

GENERIC_SUGGESTIONS = ["Daha karanlık olsun", "Daha az bilinen filmler", "Sadece Avrupa yapımları"]
EMPTY_SUGGESTIONS = ["Dönemi genişlet", "Ülke sınırını kaldır", "Farklı bir tema dene"]
OTHER_SUGGESTIONS = ["Karlı kasabalarda geçen polisiyeler", "Az bilinen psikolojik gerilimler"]
MAX_SUGGESTION_LENGTH = 60
MAX_REPLACE_CANDIDATES = 3
REPLY_FALLBACK_TEXT = (
    "Bunu şu an düzgün anlatamadım; isteğini biraz farklı yazıp bir daha dener misin?"
)
REPLACE_FAILED_TEXT = (
    "Yerine koyabileceğim, kaynağıyla doğrulanan bir film bulamadım; seçki aynı kaldı. "
    "İstersen isteği biraz değiştirip yeniden deneyebiliriz."
)

PERSON_ROLE_TEXT = {"director": "director", "actor": "actor", "any": "director or actor"}

STRUCTURED_MAX_TOKENS = 6000
UNDERSTAND_MAX_TOKENS = 4000
WRITE_MAX_TOKENS = 8000
CHAT_MAX_TOKENS = 4000


class AgentState(TypedDict, total=False):
    # Tur girdisi (her mesajla yenilenir)
    chat_id: int
    user_id: int
    user_message_id: int
    message_id: int
    text: str
    action: dict | None
    # Tur durumu (`understand` sıfırlar)
    intent: str
    request: dict
    people: list[dict]  # editörün andığı kişiler (soru ve diğer niyetlerde arşiv olgusu için)
    people_found: list[list]  # [ad, arşivdeki film sayısı]; arama sonucu
    available: int  # kişi aramasının bulduğu film sayısı (filtreler sonrası)
    protected_ids: list[int]  # kaynağı `g` ya da kişi olan adaylar: okuma sırasında öne alınır
    rank_values: dict[str, float]  # `rank_by` değeri (film kimliği metin anahtar)
    instruction: str
    target_film_id: int | None
    latest_collection_id: int | None
    base_collection_id: int | None
    exclude_ids: list[int]
    delta: int  # "N tane daha ekle / N film çıkar": göreli değişim (0 = yok)
    draft_count: int  # göreli değişimin dayandığı taslağın film sayısı
    add_only: bool  # yalnız ekleme: taslaktaki filmler kodla korunur
    candidate_ids: list[int]
    ranked_ids: list[int]
    original_request: dict
    replace_candidates: list[int]
    replace_failed: bool
    verdicts: list[dict]
    attempts: int
    applied_relax: list[str]
    tried_queries: list[str]
    notices: list[str]
    notes: list[str]
    selected_ids: list[int]
    title: str
    description: str
    suggestions: list[str]
    pending: list[dict]
    dropped: int
    step_key: str
    step_started: float
    collection_id: int | None
    steps: list[dict]
    elapsed: float


@dataclass
class Deps:
    llm: Any
    retrieval: Any


@dataclass(frozen=True)
class Understood:
    intent: str
    request: ParsedRequest | None
    instruction: str = ""
    film_id: int | None = None
    exclude_ids: tuple[int, ...] = ()
    notes: tuple[str, ...] = ()
    people: tuple[PersonHint, ...] = ()
    delta: int = 0
    draft_count: int = 0
    add_only: bool = False


_NUMBER_WORDS = frozenset(
    "bir iki üç dört beş altı yedi sekiz dokuz on yirmi".split()
)  # "birkaç" belirsiz sayıdır, listede yok


def mentions_number(text: str) -> bool:
    """Editörün bu mesajında sayı belirten öğe var mı (rakam ya da Türkçe sayı sözcüğü)? Film
    adındaki sayı ("12 Angry Men") yanlış pozitif verir; o durumda modelin değeri kabul edilir."""
    if any(char.isdigit() for char in text):
        return True
    return any(token.casefold() in _NUMBER_WORDS for token in re.findall(r"\w+", text))


def _people_lm(request: ParsedRequest) -> list[PersonLM]:
    return [PersonLM(name=person.name, role=person.role) for person in request.people]


def _previous_as_lm(previous: ParsedRequest, written: RequestLM | None) -> RequestLM:
    """Önceki isteğin modele yazdırılan biçimi; sayı alanları modelin yazdığından."""
    return RequestLM(
        en_query=previous.en_query,
        hyde=previous.hyde,
        titles=[TitleHintLM(title=hint.title, year=hint.year) for hint in previous.titles],
        filters=FiltersLM(
            year_min=previous.filters.year_min,
            year_max=previous.filters.year_max,
            countries=list(previous.filters.countries),
            max_vote_count=previous.filters.max_vote_count,
        ),
        genres=list(previous.genres),
        target_count=written.target_count if written else None,
        target_delta=written.target_delta if written else None,
        rank_by=previous.rank_by,
        theme_present=previous.theme_present,
    )


def _same_criteria(new: ParsedRequest, old: ParsedRequest) -> bool:
    """Yalnız film sayısı değişti mi? `en_query` / `hyde` model yeniden yazabilir, sayılmaz."""
    return (
        new.filters == old.filters
        and new.genres == old.genres
        and new.people == old.people
        and new.rank_by == old.rank_by
        and new.theme_present == old.theme_present
    )


def _emit(writer, event: str, payload: dict) -> None:
    writer({"event": event, "data": payload})


class StepClock:
    """Bir adımın başlangıç/bitiş olaylarını yazar ve süresini ölçer."""

    def __init__(self, writer, key: str, start_title: str, *, started: float | None = None):
        self.writer = writer
        self.key = key
        self.started = time.monotonic() if started is None else started
        if started is None:
            _emit(writer, "step.start", {"key": key, "title": start_title})

    def done(self, title: str, detail: str, count: int | None = None) -> tuple[dict, float]:
        step = {"key": self.key, "status": "done", "title": title, "detail": detail, "count": count}
        _emit(self.writer, "step.done", step)
        return step, time.monotonic() - self.started


def _notice(writer, steps: list[dict], notices: list[str], message: str) -> None:
    """Editöre bilgi: akışta `notice` olayı, kayıtlı mesajda `steps` içinde (sözleşme 1.1)."""
    _emit(writer, "notice", {"text": message})
    steps.append({"key": "notice", "status": "done", "title": "", "detail": message, "count": None})
    notices.append(message)


def chunked(items: Sequence, size: int) -> list[list]:
    return [list(items[start : start + size]) for start in range(0, len(items), size)]


async def gather_all(coroutines: Iterable[Awaitable]) -> list:
    """Eşzamanlı çalıştırır; biri hata verirse kalanları iptal eder (boşa model çağrısı kalmaz)."""
    tasks = [asyncio.ensure_future(coroutine) for coroutine in coroutines]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


def describe_request(request: ParsedRequest, instruction: str, text: str, from_action: bool) -> str:
    """Değerlendirme/seçim/yazım istemlerindeki `<request>` bölümü (veri etiketi içinde)."""
    lines = []
    if not from_action:
        lines.append(f"Editor's words (Turkish): {data.neutralize(text)}")
    lines.append(f"Search description: {data.neutralize(request.en_query)}")
    filters = request.filters
    if filters.year_min or filters.year_max:
        lines.append(f"Years: {filters.year_min or 'any'} to {filters.year_max or 'any'}")
    if filters.countries:
        lines.append("Countries: " + data.neutralize(", ".join(filters.countries)))
    if filters.max_vote_count is not None:
        lines.append("The editor wants lesser-known films.")
    if request.genres:
        named_genres = []
        for name in request.genres:
            turkish = genre_name_tr(name)
            named_genres.append(name if turkish == name else f"{name} (Turkish: {turkish})")
        lines.append("Preferred genres (soft): " + data.neutralize(", ".join(named_genres)))
    if request.people:
        named = "; ".join(
            f"{data.neutralize(person.name)} ({PERSON_ROLE_TEXT[person.role]})"
            for person in request.people
        )
        lines.append(
            f"People named by the editor (the films below are already limited to them): {named}"
        )
    if instruction:
        lines.append(f"Requested change to the current selection: {data.neutralize(instruction)}")
    return "<request>\n" + "\n".join(lines) + "\n</request>"


def validate_selection(chosen: list[int], allowed: list[int], limit: int) -> list[int]:
    """Modelin seçtiği kimlikler: listede olmayan atılır, tekrar atılır, eksik kalırsa uygun
    adaylardan sırayla tamamlanır."""
    allowed_set = set(allowed)
    result: list[int] = []
    for film_id in chosen:
        if film_id in allowed_set and film_id not in result:
            result.append(film_id)
    result = result[:limit]
    for film_id in allowed:
        if len(result) >= min(limit, len(allowed)):
            break
        if film_id not in result:
            result.append(film_id)
    return result


def rank_order(film_ids: list[int], rank_values: dict[str, float]) -> list[int]:
    """`rank_by` sırası: değeri yüksek önde; eşitlikte ve değeri olmayanda gelen sıra korunur."""
    position = {film_id: place for place, film_id in enumerate(film_ids)}
    missing = float("-inf")
    return sorted(film_ids, key=lambda fid: (-rank_values.get(str(fid), missing), position[fid]))


def _selection_facts(
    request: ParsedRequest,
    films: dict,
    people_found: list[list],
    rank_note: bool = True,
) -> dict[int, str]:
    """Gerekçe adımının film başına olguları (seçkideki sıra olgusu yok: doğrulamadan önce
    hesaplanan sıra, film düşünce yanlış kalırdı). Yalnız-ekleme turunda korunan filmler önde
    durduğundan sıralama notu verilmez (`rank_note=False`)."""
    counts = {normalize_person(name): count for name, count in people_found}
    names = [person.name for person in request.people]
    return {
        fid: data.selection_facts(
            film,
            people=names,
            rank_by=request.rank_by,
            archive_counts=counts,
            rank_note=rank_note,
        )
        for fid, film in films.items()
    }


def _fit_ids(state: AgentState) -> list[int]:
    return [v["film_id"] for v in state.get("verdicts", []) if v["verdict"] == "fit"]


def _needed(state: AgentState) -> int:
    if state["intent"] == "replace_film":
        return 1
    request = ParsedRequest.model_validate(state["request"])
    if state.get("add_only"):
        return max(1, min(request.target_count - state["draft_count"], 5))
    return min(request.target_count, 5)


def route_after_understand(state: AgentState) -> str:
    return "search" if state["intent"] in SEARCH_INTENTS else "answer"


def route_after_judge(state: AgentState) -> str:
    fit = len(_fit_ids(state))
    if fit >= _needed(state):
        return "write"
    # Kişi evreni tümüyle değerlendirildi: başka cümleyle ya da gevşek filtreyle aynı evren gelir.
    has_people = bool(ParsedRequest.model_validate(state["request"]).people)
    if not has_people and state.get("attempts", 0) < settings.AGENT["max_retries"]:
        return "retry"
    # Yalnız eklemede eldeki taslak zaten var: yeni uygun film olmasa da yazma adımına geçilir.
    return "write" if fit or state.get("add_only") else "respond"


def route_after_verify(state: AgentState) -> str:
    if state.get("replace_failed") or not state.get("selected_ids"):
        return "respond"
    return "persist"


class Nodes:
    def __init__(self, deps: Deps):
        self.llm = deps.llm
        self.retrieval = deps.retrieval
        self.cfg = settings.AGENT

    # ---------------------------------------------------------------- understand
    async def understand(self, state: AgentState) -> dict:
        writer = get_stream_writer()
        clock = StepClock(writer, "parse", "İsteğini çözüyorum")
        context = await sync_to_async(data.load_turn_context)(
            state["chat_id"], state["user_id"], state["user_message_id"]
        )
        base_request = _load_request(context.previous_request)
        understood = self._from_action(state.get("action"), context, base_request)
        if understood is None:
            understood = await self._ask_model(state["text"], context, base_request)

        detail = self._parse_detail(understood, context)
        step, seconds = clock.done("İsteğini çözdüm.", detail)
        steps = [step]
        notices: list[str] = []
        if understood.intent == "new_search" and context.draft_status == "approved":
            # Davranış zaten doğru (onaylı seçki değişmez); editöre de söylenir.
            _notice(writer, steps, notices, texts.APPROVED_UNTOUCHED_NOTICE)
        base_open = context.draft_status == "draft"
        return {
            "intent": understood.intent,
            "request": understood.request.model_dump() if understood.request else {},
            "people": [person.model_dump() for person in understood.people],
            "people_found": [],
            "available": 0,
            "protected_ids": [],
            "rank_values": {},
            "instruction": understood.instruction,
            "target_film_id": understood.film_id,
            "latest_collection_id": context.draft_id,
            "base_collection_id": (
                context.draft_id
                if understood.intent in ("refine", "replace_film") and base_open
                else None
            ),
            "exclude_ids": list(understood.exclude_ids),
            "delta": understood.delta,
            "draft_count": understood.draft_count,
            "add_only": understood.add_only,
            "candidate_ids": [],
            "ranked_ids": [],
            "original_request": understood.request.model_dump() if understood.request else {},
            "replace_candidates": [],
            "replace_failed": False,
            "verdicts": [],
            "attempts": 0,
            "applied_relax": [],
            "tried_queries": [],
            "notices": notices,
            "notes": list(understood.notes),
            "selected_ids": [],
            "title": "",
            "description": "",
            "suggestions": [],
            "pending": [],
            "dropped": 0,
            "collection_id": None,
            "steps": steps,
            "elapsed": seconds,
        }

    def _from_action(self, action, context, base_request) -> Understood | None:
        """Düğme eylemleri modele sorulmadan niyete çevrilir."""
        if not action or base_request is None or context.draft_id is None:
            return None
        draft_ids = tuple(film_id for film_id, _, _ in context.draft_films)
        if action["type"] == "replace_film":
            if context.draft_status != "draft" or action.get("film_id") not in draft_ids:
                return None
            return Understood(
                "replace_film",
                base_request,
                film_id=action["film_id"],
                exclude_ids=draft_ids,
                people=tuple(base_request.people),
            )
        if action["type"] == "research":
            return Understood(
                "new_search", base_request, exclude_ids=draft_ids, people=tuple(base_request.people)
            )
        return None

    async def _ask_model(self, text: str, context, base_request) -> Understood:
        if context.draft_model_names:
            # Çift ad biçimi: editör özgün adı da yazabilir ("Innocence'ı çıkar").
            draft_lines = "\n".join(
                f"- [{film_id}] {name}"
                for (film_id, _, _), name in zip(
                    context.draft_films, context.draft_model_names, strict=True
                )
            )
        else:
            draft_lines = "\n".join(
                f"- [{film_id}] {data.neutralize(title)}" + (f" ({year})" if year else "")
                for film_id, title, year in context.draft_films
            )
        parts = [f"<user_message>{data.neutralize(text)}</user_message>"]
        if base_request is not None:
            parts.append(
                "<previous_request>"
                # `target_stated` yalnız editöre söylenen metinler içindir; anlama istemi değişmez.
                + json.dumps(base_request.model_dump(exclude={"target_stated"}), ensure_ascii=False)
                + "</previous_request>"
            )
        if context.draft_id is not None:
            draft_title = data.neutralize(context.draft_title)
            parts.append(
                f"<draft>\nstatus: {context.draft_status}\ntitle: {draft_title}\n"
                f"films:\n{draft_lines}\n</draft>"
            )
        if context.history:
            history = "\n".join(
                f"{role}: {data.neutralize(line)}" for role, line in context.history
            )
            parts.append(f"<history>\n{history}\n</history>")

        user = "\n".join(parts)
        out = await self._ask_structured(user)
        reasked = (
            base_request is not None
            and out.intent == "refine"
            and bool(out.instruction.strip())
            and (out.request is None or not out.request.en_query.strip())
        )
        if reasked:
            # Değişiklik söylenmiş ama istek boş: ölçütler sessizce eskisiyle sürmesin diye bir kez
            # daha sorulur.
            out = await self._ask_structured(f"{user}\n{prompts.REASK_NOTE}")
        return self._normalize(out, context, base_request, text, reasked=reasked)

    async def _ask_structured(self, user: str) -> UnderstandOutput:
        return await self.llm.structured(
            step="parse",
            system=prompts.UNDERSTAND_SYSTEM,
            user=user,
            output=UnderstandOutput,
            effort=self.cfg["efforts"]["parse"],
            max_tokens=UNDERSTAND_MAX_TOKENS,
        )

    def _normalize(
        self, out: UnderstandOutput, context, base_request, text: str, *, reasked: bool = False
    ) -> Understood:
        """Modelin niyetini mevcut duruma göre düzeltir (taslak yokken refine olmaz vb.)."""
        draft_ids = tuple(film_id for film_id, _, _ in context.draft_films)
        draft_open = context.draft_status == "draft"
        intent = out.intent
        film_id = out.film_id
        people = tuple(clean_people(out.people))

        if intent == "replace_film" and not (draft_open and film_id in draft_ids and base_request):
            intent = "refine" if out.request else "other"
            if intent == "other":
                return Understood("other", None, notes=("film_not_found",), people=people)
        # Model düzeltme dediyse (taslak açık olmasa bile) önceki sayıyı kopyalamış olabilir.
        continues = intent == "refine" and base_request is not None
        if intent == "refine" and not draft_open:
            intent = "new_search"
        if intent == "question" and context.draft_id is None:
            return Understood("other", None, notes=("no_draft_to_ask_about",), people=people)

        if intent in ("new_search", "refine"):
            if intent == "refine" and base_request is not None:
                if out.request is None or not out.request.en_query.strip():
                    # Boş ya da eksik istek "ölçütler değişmedi" demektir: önceki istekle sürülür,
                    # yalnız modelin yazdığı sayı alanları alınır. Yeniden sorulduğu halde hâlâ
                    # boşsa ve değişiklik söylenmişse yalnız sayı değişimi bunu taşıyabilir.
                    number_given = (
                        out.request is not None
                        and (out.request.target_delta or out.request.target_count is not None)
                        and mentions_number(text)
                    )
                    if reasked and not number_given:
                        raise LLMError(MSG_BAD_OUTPUT)
                    out = out.model_copy(
                        update={
                            "request": _previous_as_lm(base_request, out.request),
                            "people": out.people or _people_lm(base_request),
                        }
                    )
            if out.request is None or not out.request.en_query.strip():
                raise LLMError(MSG_BAD_OUTPUT)
            # Sayı ve "söylendi" bayrağı yalnız aynı seçkiyi sürdüren turda (refine) önceki
            # istekten devralınır; yeni konuda söylenmediyse 10 ve söylenmedi.
            inherit = intent == "refine" and base_request is not None
            raw = out.request
            if not mentions_number(text):
                # Mesajda sayı yok: modelin yazdığı sayı uydurmadır, "söylendi" sayılmaz.
                raw = raw.model_copy(update={"target_count": None, "target_delta": None})
            request = sanitize_request(
                raw,
                fallback_target=base_request.target_count if inherit else 10,
                fallback_stated=base_request.target_stated if inherit else False,
                previous=base_request if continues else None,
                people=out.people,
            )
            delta, add_only, exclude = 0, False, ()
            refining_draft = intent == "refine" and draft_open and bool(draft_ids)
            target = None
            if refining_draft and raw.target_delta:
                # Göreli sayı kodla hesaplanır: model toplamı yanlış yazsa da değişim kazanır.
                delta = raw.target_delta
                target = min(max(len(draft_ids) + delta, MIN_TARGET), MAX_TARGET)
                request = request.model_copy(update={"target_count": target, "target_stated": True})
            elif refining_draft and raw.target_count is not None:
                target = request.target_count
            instruction = out.instruction.strip()
            only_count_changes = (
                target is not None
                and base_request is not None
                and not instruction
                and _same_criteria(request, base_request)
            )
            grows = target is not None and target > len(draft_ids)
            # Yalnız ekleme ("2 tane daha", "toplam 8 film olsun"): taslaktaki filmler kodla
            # korunur. Taslak zaten 20 filmse hedef 20'de kalır ve taslak aynen kalır
            # (delta > 0, fark 0). Model `keep_draft` derse ölçüt değişse de mevcut filmler kalır.
            if (only_count_changes and (grows or (delta > 0 and target >= 20))) or (
                out.keep_draft and grows
            ):
                delta = delta or target - len(draft_ids)
                # Ölçüt değişmediyse önceki istek aynen sürer; değiştiyse (model değişikliği
                # `instruction`a yazmasa da) eklenenler yeni istekle aranır ve taslağın kayıtlı
                # isteği o olur.
                changed = (
                    bool(instruction)
                    or base_request is None
                    or not _same_criteria(request, base_request)
                )
                kept = request if changed else base_request
                request = kept.model_copy(update={"target_count": target, "target_stated": True})
                add_only, exclude = True, draft_ids
            return Understood(
                intent,
                request,
                instruction=instruction,
                exclude_ids=exclude,
                people=tuple(request.people),
                delta=delta,
                draft_count=len(draft_ids) if (delta or add_only) else 0,
                add_only=add_only,
            )
        if intent == "replace_film":
            return Understood(
                intent,
                base_request,
                film_id=film_id,
                exclude_ids=draft_ids,
                people=tuple(base_request.people),
            )
        if intent == "question":
            return Understood(
                intent, None, film_id=film_id if film_id in draft_ids else None, people=people
            )
        return Understood("other", None, people=people)

    def _parse_detail(self, understood: Understood, context) -> str:
        if understood.intent in ("new_search", "refine"):
            return texts.request_summary(understood.request)
        if understood.intent == "replace_film":
            title = next(
                (title for fid, title, _ in context.draft_films if fid == understood.film_id), ""
            )
            return f"“{title}” yerine başka bir film arıyorum."
        if understood.intent == "question":
            return "Taslaktaki filmlerle ilgili bir soru."
        return ""

    # ---------------------------------------------------------------- search
    async def search(self, state: AgentState) -> dict:
        writer = get_stream_writer()
        clock = StepClock(writer, "search", "Arşivde dolaşıyorum")
        request = ParsedRequest.model_validate(state["request"])
        result = await self.retrieval.search(
            request,
            limit=self.cfg["search_depth"],
            exclude_film_ids=state.get("exclude_ids", []),
        )
        steps = list(state["steps"])
        notices = list(state["notices"])
        ids = [candidate.film_id for candidate in result.candidates]
        # `g` ve kişi adayları okuma sınırında korunur; `rank_by` değerleri seçimde kullanılır.
        protected = list(state.get("protected_ids", []))
        protected += [
            c.film_id
            for c in result.candidates
            if ("g" in c.sources or "person" in c.sources) and c.film_id not in protected
        ]
        rank_values = dict(state.get("rank_values", {}))
        rank_values.update(
            {str(c.film_id): c.rank_value for c in result.candidates if c.rank_value is not None}
        )
        title, detail = texts.search_done(len(ids))
        step, seconds = clock.done(title, detail, len(ids))
        steps.append(step)
        if request.people:
            relaxed = texts.people_filter_notice(tuple(result.relaxed_filters))
        else:
            relaxed = texts.relaxed_filter_notice(tuple(result.relaxed_filters))
        if relaxed:
            _notice(writer, steps, notices, relaxed)
        update: dict = {}
        if request.people_only and not request.target_stated and not state["instruction"]:
            # Sayı söylenmedi, istek yalnız kişi: hedef kişinin filmlerinin sayısıdır (en çok 20).
            target = min(len(ids), MAX_TARGET)
            if ids and target != request.target_count:
                update["request"] = request.model_copy(update={"target_count": target}).model_dump()
        # Bütün denemelerin adayları, bulundukları sırayla birikir (önce ilk denemeler).
        ranked = list(state.get("ranked_ids", []))
        seen = set(ranked)
        ranked += [film_id for film_id in ids if film_id not in seen]
        return {
            "candidate_ids": ids,
            "ranked_ids": ranked,
            "protected_ids": protected,
            "rank_values": rank_values,
            "people_found": [[name, count] for name, count in result.people_found],
            "available": len(ids),
            "steps": steps,
            "notices": notices,
            "elapsed": state["elapsed"] + seconds,
            **update,
        }

    # ---------------------------------------------------------------- judge
    async def judge(self, state: AgentState) -> dict:
        writer = get_stream_writer()
        clock = StepClock(writer, "read", "Hikâyelerini okuyorum")
        request = ParsedRequest.model_validate(state["request"])
        judged = {verdict["film_id"]: verdict for verdict in state["verdicts"]}

        pool = [fid for fid in state["candidate_ids"] if fid not in judged]
        # Model önerisi (g) ve kişi adayları okuma sınırı dolsa da okunur: listenin başına alınır.
        protected = set(state.get("protected_ids", []))
        pool = [fid for fid in pool if fid in protected] + [
            fid for fid in pool if fid not in protected
        ]
        # Yalnız kişi isteğinde eleme yoktur: kişinin filmleri veritabanından gelir, hepsi uygun.
        skip = (request.people_only and not state["instruction"]) or (
            bool(request.people) and not pool
        )
        if not skip:
            pool = pool[: self._read_limit(request)]
        if (
            state["intent"] == "refine"
            and state.get("base_collection_id")
            and not state.get("add_only")
        ):
            # Taslaktaki mevcut filmler de yeni isteğe göre yeniden değerlendirilir.
            draft_ids = await sync_to_async(data.draft_film_ids)(state["base_collection_id"])
            if request.people:
                # Kişi kısıtı taslağın eski filmlerine de uygulanır (evren aramayla aynı kuraldan).
                universe = await self._people_universe(request)
                draft_ids = [fid for fid in draft_ids if fid in universe]
            pool += [fid for fid in draft_ids if fid not in judged and fid not in pool]
        if skip:
            for film_id in pool:
                judged[film_id] = {"film_id": film_id, "verdict": "fit", "reason": ""}
            title, detail = texts.read_skipped(len(pool))
            step, seconds = clock.done(title, detail, len(pool))
            return {
                "verdicts": list(judged.values()),
                "steps": [*state["steps"], step],
                "elapsed": state["elapsed"] + seconds,
            }

        films = await sync_to_async(data.load_judge_films)(pool)
        pool = [fid for fid in pool if fid in films]
        brief = describe_request(
            request, state["instruction"], state["text"], bool(state.get("action"))
        )
        chunks = chunked(pool, self.cfg["judge_chunk"])
        outputs = await gather_all(self._judge_chunk(brief, films, chunk) for chunk in chunks)
        for chunk_verdicts in outputs:
            for verdict in chunk_verdicts:
                judged[verdict["film_id"]] = verdict

        verdicts = list(judged.values())
        fit = sum(1 for verdict in verdicts if verdict["verdict"] == "fit")
        title, detail = texts.read_done(fit)
        step, seconds = clock.done(title, detail, fit)
        return {
            "verdicts": verdicts,
            "steps": [*state["steps"], step],
            "elapsed": state["elapsed"] + seconds,
        }

    def _read_limit(self, request: ParsedRequest) -> int:
        """Okunacak en çok aday: kişi evreni tümüyle okunur (arama derinliğine kadar)."""
        return self.cfg["search_depth"] if request.people else self.cfg["judge_limit"]

    async def _people_universe(self, request: ParsedRequest) -> set[int]:
        """İstekteki kişilerin arşivdeki filmleri; aramadaki kişi dizini ve kuralıyla aynı."""
        found = await self.retrieval.people_films(
            [(person.name, person.role) for person in request.people]
        )
        return {film_id for _, _, film_ids in found for film_id in film_ids}

    async def _judge_chunk(self, brief: str, films: dict, chunk: list[int]) -> list[dict]:
        try:
            return await self._judge_ask(brief, films, chunk)
        except LLMRefused:
            if not self.cfg.get("skip_refused"):
                raise
        # Reddedilen küme ikiye bölünür (tek düzey); yine reddedilen yarı "uymuyor" sayılır.
        # Tek adayda aynı soru yinelenmez.
        middle = (len(chunk) + 1) // 2
        halves = [chunk[:middle], chunk[middle:]] if len(chunk) > 1 else []
        verdicts = []
        refused = list(chunk) if not halves else []
        for half in halves:
            try:
                verdicts += await self._judge_ask(brief, films, half)
            except LLMRefused:
                refused += half
        verdicts += [{"film_id": fid, "verdict": "no", "reason": ""} for fid in refused]
        logger.warning("llm step=judge %d aday reddedildiği için elendi", len(refused))
        return sorted(verdicts, key=lambda verdict: chunk.index(verdict["film_id"]))

    async def _judge_ask(self, brief: str, films: dict, chunk: list[int]) -> list[dict]:
        blocks = "\n".join(data.format_judge_film(films[film_id]) for film_id in chunk)
        out: JudgeOutput = await self.llm.structured(
            step="judge",
            system=prompts.JUDGE_SYSTEM,
            user=f"{brief}\n<films>\n{blocks}\n</films>",
            output=JudgeOutput,
            effort=self.cfg["efforts"]["judge"],
            max_tokens=STRUCTURED_MAX_TOKENS,
        )
        by_id = {}
        for verdict in out.verdicts:
            if verdict.film_id in chunk:  # parçada olmayan kimlik yok sayılır
                by_id[verdict.film_id] = {
                    "film_id": verdict.film_id,
                    "verdict": verdict.verdict,
                    "reason": verdict.reason.strip(),
                }
        # Cevapta hiç yer almayan film uygun sayılmaz.
        return [
            by_id.get(film_id, {"film_id": film_id, "verdict": "no", "reason": ""})
            for film_id in chunk
        ]

    # ---------------------------------------------------------------- retry
    async def retry(self, state: AgentState) -> dict:
        writer = get_stream_writer()
        clock = StepClock(writer, "retry", "Aramayı genişletiyorum")
        attempt = state["attempts"] + 1
        request = ParsedRequest.model_validate(state["request"])
        applied = list(state["applied_relax"])
        tried = list(state["tried_queries"])
        steps = list(state["steps"])
        notices = list(state["notices"])

        plan = relax.next_relaxation(request, applied)
        if plan is not None:
            request, key = plan
            applied.append(key)
            message = relax.RELAX_NOTICES[key]
        else:
            tried.append(request.en_query)
            alternative = await self._alternative_query(request, tried)
            request = request.model_copy(
                update={
                    "en_query": alternative.en_query.strip() or request.en_query,
                    "hyde": alternative.hyde.strip() or request.hyde,
                    "titles": [],
                }
            )
            message = relax.ALT_QUERY_NOTICE

        step, seconds = clock.done("Aramayı genişlettim.", f"{attempt}. yeniden deneme.", attempt)
        steps.append(step)
        _notice(writer, steps, notices, message)
        return {
            "request": request.model_dump(),
            "attempts": attempt,
            "applied_relax": applied,
            "tried_queries": tried,
            "steps": steps,
            "notices": notices,
            "elapsed": state["elapsed"] + seconds,
        }

    async def _alternative_query(self, request: ParsedRequest, tried: list[str]) -> AltQueryOutput:
        tried_lines = "\n".join(f"- {data.neutralize(query)}" for query in tried)
        user = (
            f"<request>\nSearch description: {data.neutralize(request.en_query)}\n</request>\n"
            f"<tried>\n{tried_lines}\n</tried>"
        )
        return await self.llm.structured(
            step="retry",
            system=prompts.ALT_QUERY_SYSTEM,
            user=user,
            output=AltQueryOutput,
            effort=self.cfg["efforts"]["parse"],
            max_tokens=UNDERSTAND_MAX_TOKENS,
        )

    # ---------------------------------------------------------------- write
    async def write(self, state: AgentState) -> dict:
        writer = get_stream_writer()
        updating = state["intent"] in ("refine", "replace_film")
        key = "update" if updating else "select"
        clock = StepClock(
            writer, key, "Seçkiyi güncelliyorum" if updating else "En iyilerini seçiyorum"
        )
        request = ParsedRequest.model_validate(state["request"])
        base_id = state.get("base_collection_id")
        base_ids = await sync_to_async(data.draft_film_ids)(base_id) if base_id else []

        fit = set(_fit_ids(state))
        ordered = [fid for fid in state.get("ranked_ids", []) if fid in fit]
        ordered += [fid for fid in base_ids if fid in fit and fid not in ordered]
        if state["intent"] == "replace_film":
            ordered = [fid for fid in ordered if fid not in base_ids]
        ordered = ordered[: self._read_limit(request) + len(base_ids)]

        if state.get("add_only"):
            # Taslaktaki filmler sırasıyla ve gerekçeleriyle kalır; yalnız eksik kadar yeni eklenir.
            fresh = [fid for fid in ordered if fid not in base_ids]
            if request.rank_by:
                fresh = rank_order(fresh, state.get("rank_values", {}))
            selected = [*base_ids, *fresh[: request.target_count - len(base_ids)]]
            title, description = await sync_to_async(data.base_texts)(base_id)
            suggestions = []
            replace_candidates = []
        elif state["intent"] == "replace_film":
            # En çok 3 aday: ilki yazılır, tutmazsa `verify` sıradakini dener.
            replace_candidates = ordered[:MAX_REPLACE_CANDIDATES]
            selected = [
                replace_candidates[0] if fid == state["target_film_id"] else fid for fid in base_ids
            ]
            title, description = await sync_to_async(data.base_texts)(base_id)
            suggestions: list[str] = []
        else:
            replace_candidates = []
            selected, title, description, suggestions = await self._select(
                state, request, ordered, base_id, base_ids
            )

        new_ids = [fid for fid in selected if fid not in base_ids]
        # Hepsi reddedilirse tur ret mesajıyla biter; film değiştirmede ilk adayın reddi
        # `verify`'ın sıradaki adayı denemesine bırakılır, taslakta kalan film varsa tur sürer.
        end_if_all_refused = state["intent"] != "replace_film" and set(selected) <= set(new_ids)
        pending = await self._write_films(
            state, request, new_ids, end_if_all_refused=end_if_all_refused
        )
        return {
            "selected_ids": selected,
            "title": title,
            "description": description,
            "suggestions": suggestions,
            "pending": pending,
            "replace_candidates": replace_candidates,
            "step_key": key,
            "step_started": clock.started,
        }

    async def _select(self, state, request, ordered, base_id, base_ids):
        films = await sync_to_async(data.load_judge_films)(ordered)
        available = [fid for fid in ordered if fid in films]
        fixed: list[int] | None = None
        if request.rank_by:
            # Sıra ve kesme kodla: modelin seçimi bu sırayı değiştiremez.
            fixed = rank_order(available, state.get("rank_values", {}))[: request.target_count]
        reasons = {v["film_id"]: v["reason"] for v in state["verdicts"]}
        lines = "\n".join(
            data.format_candidate_line(films[fid], reasons.get(fid, ""), fid in base_ids)
            for fid in (available if fixed is None else fixed)
        )
        brief = describe_request(
            request, state["instruction"], state["text"], bool(state.get("action"))
        )
        parts = [brief, f"target_count: {request.target_count}"]
        if fixed is not None:
            parts.append("order_fixed: true")
        parts.append(f"<films>\n{lines}\n</films>")
        if base_id:
            current_title, current_description = await sync_to_async(data.base_texts)(base_id)
            parts.append(
                "<current_selection>\n"
                f"title: {data.neutralize(current_title)}\n"
                f"description: {data.neutralize(current_description)}\n"
                "</current_selection>"
            )
        out: SelectOutput = await self.llm.structured(
            step="select",
            system=prompts.SELECT_SYSTEM,
            user="\n".join(parts),
            output=SelectOutput,
            effort=self.cfg["efforts"]["write"],
            max_tokens=STRUCTURED_MAX_TOKENS,
        )
        if fixed is not None:
            selected = fixed
        else:
            selected = validate_selection(out.selected_ids, available, request.target_count)
        title = out.title.strip()[:200]
        description = out.description.strip()
        # Türkçe olmayan başlık/açıklama editöre gösterilmez: güvenli varsayılana düşülür.
        # Başlık kısa olduğu için dil denetimi Türkçe başlığı da reddedebilir ("70'lerin
        # Paranoyak Siyasi Gerilimleri"): aynı cevaptaki açıklama Türkçeyse başlık kabul edilir.
        description_ok = bool(description) and language.looks_turkish(description)
        if not title or not (language.looks_turkish(title) or description_ok):
            title = texts.request_summary(request)[:200]
        if not description_ok:
            description = ""
        suggestions = [
            s.strip()
            for s in out.suggestions
            if s.strip() and len(s.strip()) <= MAX_SUGGESTION_LENGTH
        ][:3]
        return selected, title, description, suggestions

    async def _write_films(
        self, state, request, film_ids: list[int], problems=None, *, end_if_all_refused=False
    ) -> list[dict]:
        if not film_ids:
            return []
        films = await sync_to_async(data.load_source_films)(film_ids)
        facts = _selection_facts(
            request, films, state.get("people_found", []), rank_note=not state.get("add_only")
        )
        brief = describe_request(
            request, state["instruction"], state["text"], bool(state.get("action"))
        )
        chunks = chunked([fid for fid in film_ids if fid in films], self.cfg["write_chunk"])
        outputs = await gather_all(
            self._write_chunk(brief, films, facts, chunk, problems) for chunk in chunks
        )
        if end_if_all_refused and chunks and all(items is None for items in outputs):
            raise LLMRefused()
        return [item for chunk_items in outputs for item in chunk_items or []]

    async def _write_chunk(
        self, brief, films, facts: dict[int, str], chunk: list[int], problems=None
    ) -> list[dict] | None:
        """Gerekçeler; `skip_refused` açıkken model reddederse None (film `verify`'da düşer)."""
        blocks = "\n".join(data.format_source_film(films[fid], facts.get(fid, "")) for fid in chunk)
        user = f"{brief}\n<films>\n{blocks}\n</films>"
        if problems:
            lines = "\n".join(f"film {fid}: {problems[fid]}" for fid in chunk if fid in problems)
            user += f"\n<problems>\n{lines}\n</problems>"
        try:
            out: WriteOutput = await self.llm.structured(
                step="write",
                system=prompts.WRITE_SYSTEM,
                user=user,
                output=WriteOutput,
                effort=self.cfg["efforts"]["write"],
                max_tokens=WRITE_MAX_TOKENS,
            )
        except LLMRefused as refused:
            if not self.cfg.get("skip_refused"):
                raise
            logger.warning(
                "llm step=write film_id=%s reddedildi, taslaga girmedi block_reason=%s",
                ",".join(str(fid) for fid in chunk),
                refused.reason,
            )
            return None
        return [writing.model_dump() for writing in out.films]

    # ---------------------------------------------------------------- verify
    async def verify(self, state: AgentState) -> dict:
        writer = get_stream_writer()
        if state["intent"] == "replace_film":
            return await self._verify_replacement(state, writer)
        request = ParsedRequest.model_validate(state["request"])
        base_id = state.get("base_collection_id")
        base_ids = await sync_to_async(data.draft_film_ids)(base_id) if base_id else []
        new_ids = [fid for fid in state["selected_ids"] if fid not in base_ids]

        films = await sync_to_async(data.load_source_films)(new_ids)
        writings = [_writing(item) for item in state["pending"]]
        verified, problems = verify_writings(writings, set(new_ids), films)

        if problems:
            # Tek onarım çağrısı: yalnız tutmayan filmler, sorun ayrıntısıyla.
            repaired = await self._write_films(
                state, request, [fid for fid in new_ids if fid in problems], problems
            )
            again, problems = verify_writings(
                [_writing(item) for item in repaired], set(problems), films
            )
            verified.update(again)

        dropped_ids = set(new_ids) - set(verified)
        selected = [fid for fid in state["selected_ids"] if fid not in dropped_ids]
        if dropped_ids:
            logger.warning("Alıntısı doğrulanamayan %d film taslağa alınmadı", len(dropped_ids))

        updating = state["intent"] in ("refine", "replace_film")
        clock = StepClock(writer, state["step_key"], "", started=state["step_started"])
        changed = len(verified)
        if updating:
            title = "Seçkiyi güncelledim."
            detail = f"{changed} film değişti." if changed else "Seçkideki filmler aynı kaldı."
        else:
            title = f"En iyi {texts.acc(len(selected))} seçtim" if selected else "Seçim yapamadım."
            detail = "ve her biri için nedenini yazdım." if selected else ""
        if dropped_ids:
            detail = (
                f"{detail} {len(dropped_ids)} film, alıntısı doğrulanamadığı için dışarıda kaldı."
            )
        step, seconds = clock.done(
            title, detail.strip(), len(selected) if not updating else changed
        )
        return {
            "selected_ids": selected,
            "pending": [item.model_dump() for item in verified.values()],
            "dropped": len(dropped_ids),
            "steps": [*state["steps"], step],
            "elapsed": state["elapsed"] + seconds,
        }

    async def _verify_replacement(self, state: AgentState, writer) -> dict:
        """Yeni film doğrulanamazsa sıradaki aday denenir (en çok 3 yazım çağrısı); hiçbiri
        tutmazsa hedef film taslakta KALIR ve taslak değişmez."""
        request = ParsedRequest.model_validate(state["request"])
        base_ids = await sync_to_async(data.draft_film_ids)(state["base_collection_id"])
        candidates = state["replace_candidates"]
        films = await sync_to_async(data.load_source_films)(candidates)

        writings = [_writing(item) for item in state["pending"]]  # ilk adayın yazımı
        chosen = None
        dropped = 0
        for index, film_id in enumerate(candidates):
            if index:
                items = await self._write_films(state, request, [film_id])
                writings = [_writing(item) for item in items]
            verified, _ = verify_writings(writings, {film_id}, films)
            if film_id in verified:
                chosen = verified[film_id]
                break
            dropped += 1
        if dropped:
            logger.warning("Alıntısı doğrulanamayan %d aday film elendi", dropped)

        clock = StepClock(writer, state["step_key"], "", started=state["step_started"])
        if chosen is None:
            step, seconds = clock.done(
                "Seçkiyi güncelleyemedim.",
                "Kaynağıyla doğrulanan bir yedek film bulamadım; seçki aynı kaldı.",
                0,
            )
            selected, pending = list(base_ids), []
        else:
            detail = "1 film değişti."
            if dropped:
                detail += f" {dropped} aday, alıntısı doğrulanamadığı için elendi."
            step, seconds = clock.done("Seçkiyi güncelledim.", detail, 1)
            target = state["target_film_id"]
            selected = [chosen.film_id if film_id == target else film_id for film_id in base_ids]
            pending = [chosen.model_dump()]
        return {
            "selected_ids": selected,
            "pending": pending,
            "dropped": dropped,
            "replace_failed": chosen is None,
            "steps": [*state["steps"], step],
            "elapsed": state["elapsed"] + seconds,
        }

    # ---------------------------------------------------------------- persist
    async def persist(self, state: AgentState) -> dict:
        writer = get_stream_writer()
        base_id = state.get("base_collection_id")
        writings = {item["film_id"]: item for item in state["pending"]}
        entries: list[KeptFilm | NewFilm] = []
        for film_id in state["selected_ids"]:
            item = writings.get(film_id)
            if item is None:
                entries.append(KeptFilm(film_id))
                continue
            entries.append(
                NewFilm(
                    film_id=film_id,
                    rationale=item["rationale"],
                    source_quote=item["source_quote"],
                    source_kind=item["source_kind"],
                )
            )
        collection = await sync_to_async(data.persist_draft)(
            chat_id=state["chat_id"],
            user_id=state["user_id"],
            request=state["original_request"],
            title=state["title"],
            description=state["description"],
            entries=entries,
            base_id=base_id,
        )
        _emit(writer, "collection", collection)
        return {"collection_id": collection["id"]}

    # ---------------------------------------------------------------- respond / answer
    async def respond(self, state: AgentState) -> dict:
        writer = get_stream_writer()
        if state.get("replace_failed"):
            # Gerçeği kodla söyler: model yorumuna bırakılmaz, taslak değişmedi.
            reply = REPLACE_FAILED_TEXT
            for word in reply.split(" "):
                _emit(writer, "text.delta", {"delta": word + " "})
            return await self._finish(state, writer, reply, GENERIC_SUGGESTIONS, None)
        collection_id = state.get("collection_id")
        request = ParsedRequest.model_validate(state["request"])
        notes = list(state.get("notes", []))
        replacing = state["intent"] == "replace_film"
        if replacing:
            # Tek film değişiminde yalnız o turla ilgili notlar gider: arama gevşetme bildirimleri,
            # eksik sayı ve kısmi eşleşme notları bu cevapta anlamsız kalır.
            if state.get("dropped"):
                notes.append(
                    f"{state['dropped']} replacement candidate(s) were skipped because the quote "
                    "for their justification could not be verified; the next candidate was used."
                )
            if collection_id:
                old_id = state.get("target_film_id")
                new_id = state["pending"][0]["film_id"] if state.get("pending") else None
                names = await sync_to_async(data.film_title_lines)(
                    [fid for fid in (old_id, new_id) if fid is not None]
                )
                notes.append(texts.replace_note(names.get(old_id), names.get(new_id)))
        else:
            notes += [f"Already told the editor: {message}" for message in state["notices"]]
            if state.get("dropped"):
                notes.append(
                    f"{state['dropped']} film(s) were left out because the quote for their "
                    "justification could not be verified in the source text."
                )
            if state.get("people_found"):
                found = [(data.neutralize(name), count) for name, count in state["people_found"]]
                notes += texts.people_notes(found, request, state.get("available", 0))
            partial = sum(1 for v in state["verdicts"] if v["verdict"] == "partial")
            delta = state.get("delta", 0)
            if collection_id:
                # Sayı kaydedilen taslaktan okunur; modele sayım ya da çıkarım bırakılmaz.
                count = await sync_to_async(data.collection_film_count)(collection_id)
                if delta and (state.get("add_only") or delta < 0):
                    notes.append(texts.change_note(delta, state["draft_count"], count))
                else:
                    notes.append(texts.count_note(count, request))
                if request.people_only and not request.target_stated:
                    universe = texts.universe_note(count, state.get("available", 0))
                    if universe:
                        notes.append(universe)
            if collection_id and partial and not state.get("add_only"):
                notes.append(f"{partial} more films matched only partly and were not included.")

        brief = describe_request(
            request, state["instruction"], state["text"], bool(state.get("action"))
        )
        if collection_id:
            lines = await sync_to_async(data.collection_lines)(collection_id)
            title, description = await sync_to_async(data.base_texts)(collection_id)
            collection_part = (
                f"<collection>\ntitle: {data.neutralize(title)}\n"
                f"description: {data.neutralize(description)}\nfilms:\n{lines}\n</collection>"
            )
            suggestions = state.get("suggestions") or GENERIC_SUGGESTIONS
        else:
            collection_part = "<outcome>no_collection: nothing suitable was found</outcome>"
            suggestions = EMPTY_SUGGESTIONS
        notes = [texts.NOTES_HEADER, *notes]
        user = f"{brief}\n{collection_part}\n<notes>\n" + "\n".join(notes) + "\n</notes>"
        film_ids = {v["film_id"] for v in state["verdicts"]} | {state.get("target_film_id")}
        if collection_id:
            film_ids |= set(await sync_to_async(data.draft_film_ids)(collection_id))
        titles = await sync_to_async(data.film_names)([fid for fid in film_ids if fid])
        reply = await self._stream(writer, prompts.RESPOND_SYSTEM, user, "respond", titles)
        return await self._finish(state, writer, reply, suggestions, collection_id)

    async def answer(self, state: AgentState) -> dict:
        writer = get_stream_writer()
        parts = [f"<user_message>{data.neutralize(state['text'])}</user_message>"]
        latest = state.get("latest_collection_id")
        film_ids: set[int] = set()
        if state["intent"] == "question" and latest:
            film_ids |= set(await sync_to_async(data.draft_film_ids)(latest))
            texts_block = await sync_to_async(data.load_answer_texts)(
                latest, state.get("target_film_id")
            )
            parts.append(f"<draft>\n{texts_block}\n</draft>")
        people = state.get("people", [])
        if people:
            # Arşiv hakkında konuşmak için olgu: arama yapılmadı, kişi dizininden okunur.
            counts = await self.retrieval.people_films(
                [(person["name"], person["role"]) for person in people]
            )
            entries = [
                (name, person["role"], count, film_ids)
                for person, (name, count, film_ids) in zip(people, counts, strict=True)
            ]
            film_ids |= {film_id for _, _, _, ids in entries for film_id in ids}
            block = await sync_to_async(data.archive_block)(entries)
            parts.append(f"<archive>\n{block}\n</archive>")
        for note in state.get("notes", []):
            parts.append(f"<notes>{note}</notes>")
        titles = await sync_to_async(data.film_names)(list(film_ids))
        reply = await self._stream(
            writer, prompts.ANSWER_SYSTEM, "\n".join(parts), "answer", titles
        )
        suggestions = GENERIC_SUGGESTIONS if state["intent"] == "question" else OTHER_SUGGESTIONS
        return await self._finish(state, writer, reply, suggestions, None)

    async def _stream(self, writer, system: str, user: str, step: str, titles=()) -> str:
        """Cevap cümle cümle akar: istemciye yalnız denetimden geçmiş, tamamlanmış cümleler gider.
        Denetime takılan cümle görülünce o cümle ve sonrası gönderilmez; cevap bir kez sessizce
        yeniden üretilir (`message.done` temiz metni taşır). O da takılırsa takılan cümleleri
        atılmış ilk metin kullanılır (boşsa yedek metin)."""
        clean, blocked = await self._collect(writer, system, user, step, titles)
        if not blocked:
            return clean
        logger.warning(
            "Cevapta iç ifade ya da yabancı dil parçası var (%s); yeniden üretiliyor", step
        )
        try:
            retry, retry_blocked = await self._collect(
                None, system, f"{user}\n{prompts.REWRITE_NOTE}", step, titles
            )
        except LLMError:
            retry, retry_blocked = "", True
        if not retry_blocked:
            return retry
        logger.warning("Yeniden üretim de temiz değil (%s); takılan cümleler atıldı", step)
        return clean or REPLY_FALLBACK_TEXT

    async def _collect(self, writer, system: str, user: str, step: str, titles) -> tuple[str, bool]:
        """Cevabı cümle cümle toplar. Dönüş: (denetimden geçen cümleler, takılan cümle oldu mu).
        `writer` verilmişse temiz cümleler, ilk takılmaya kadar canlı iletilir."""
        clean: list[str] = []
        blocked = False
        seen = False

        def take(sentence: str) -> None:
            nonlocal blocked
            if language.leaks_internal_phrasing(sentence, titles, judge_language=False):
                blocked = True
                return
            clean.append(sentence)
            if writer is not None and not blocked:
                _emit(writer, "text.delta", {"delta": sentence})

        buffer = ""
        async for delta in self.llm.stream_text(
            step=step,
            system=system,
            user=user,
            effort=self.cfg["efforts"]["chat"],
            max_tokens=CHAT_MAX_TOKENS,
        ):
            seen = seen or bool(delta.strip())
            buffer += delta
            while (popped := language.pop_sentence(buffer)) is not None:
                sentence, buffer = popped
                take(sentence)
        if buffer.strip():
            take(buffer)
        if not seen:
            raise LLMError(MSG_BAD_OUTPUT)
        text = "".join(clean).strip()
        # Dil denetimi tüm metne uygulanır: tek tek kısa cümlede güvenilmez.
        return text, blocked or language.leaks_internal_phrasing(text, titles)

    async def _finish(self, state, writer, reply, suggestions, collection_id) -> dict:
        """Cevabı kaydeder ve akışı bitirir (yarım cevap hiçbir zaman kaydedilmez)."""
        suggestions = [s for s in suggestions if s][:3]
        duration = round(state.get("elapsed", 0.0), 1)

        @transaction.atomic  # mesaj, başlık ve sohbet zamanı tek işlemde (tek onay)
        def save():
            chat = Chat.objects.get(pk=state["chat_id"], user_id=state["user_id"])
            message = chat_service.save_assistant_message(
                chat,
                message_id=state["message_id"],
                text=reply,
                steps=state.get("steps", []),
                duration_s=duration,
                collection_id=collection_id,
                suggestions=suggestions,
            )
            collection_title = data.base_texts(collection_id)[0] if collection_id else None
            chat = chat_service.update_title(
                chat, collection_title=collection_title, user_text=state["text"]
            )
            return (
                chat_service.message_out(message).model_dump(mode="json"),
                chat_service.summarize(chat).model_dump(mode="json"),
            )

        message_payload, chat_payload = await sync_to_async(save)()
        _emit(writer, "suggestions", {"items": suggestions})
        _emit(writer, "message.done", {"message": message_payload, "chat": chat_payload})
        # Sonraki tur için durum küçültülür; taslak veritabanında zaten durur.
        return {
            "pending": [],
            "verdicts": [],
            "candidate_ids": [],
            "ranked_ids": [],
            "collection_id": collection_id,
        }

    # ---------------------------------------------------------------- await_editor
    async def await_editor(self, state: AgentState) -> dict:
        """Yalnız bekler: ağır iş yok (devam ederken bu düğüm baştan çalışır)."""
        message = interrupt({"type": "await_message"})
        return {
            "text": message["text"],
            "action": message.get("action"),
            "user_message_id": message["user_message_id"],
            "message_id": message["message_id"],
        }


def _load_request(raw: dict | None) -> ParsedRequest | None:
    if not raw:
        return None
    try:
        return ParsedRequest.model_validate(raw)
    except ValidationError:
        logger.warning("Kayıtlı istek okunamadı; önceki istek yok sayıldı")
        return None


def _writing(item: dict) -> FilmWriting:
    return FilmWriting.model_validate(item)


def build_graph(deps: Deps, checkpointer):
    nodes = Nodes(deps)
    builder = StateGraph(AgentState)
    builder.add_node("understand", nodes.understand)
    builder.add_node("search", nodes.search)
    builder.add_node("judge", nodes.judge)
    builder.add_node("retry", nodes.retry)
    builder.add_node("write", nodes.write)
    builder.add_node("verify", nodes.verify)
    builder.add_node("persist", nodes.persist)
    builder.add_node("respond", nodes.respond)
    builder.add_node("answer", nodes.answer)
    builder.add_node("await_editor", nodes.await_editor)

    builder.add_edge(START, "understand")
    builder.add_conditional_edges("understand", route_after_understand, ["search", "answer"])
    builder.add_edge("search", "judge")
    builder.add_conditional_edges("judge", route_after_judge, ["write", "retry", "respond"])
    builder.add_edge("retry", "search")
    builder.add_edge("write", "verify")
    builder.add_conditional_edges("verify", route_after_verify, ["persist", "respond"])
    builder.add_edge("persist", "respond")
    builder.add_edge("respond", "await_editor")
    builder.add_edge("answer", "await_editor")
    builder.add_edge("await_editor", "understand")
    return builder.compile(checkpointer=checkpointer)
