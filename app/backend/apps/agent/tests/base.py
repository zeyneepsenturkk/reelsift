"""Test yardımcıları: sahte dil modeli ve sahte arama servisi (servis sınırında verilir).

Sahte model gerçek istemlerin içindeki etiketli bölümleri okur ve onlara göre cevap verir:
böylece düğümlerin istem kurma, cevap doğrulama ve alıntı denetimi kodu gerçekten çalışır.
"""

import asyncio
import re
from dataclasses import dataclass, field

from asgiref.sync import sync_to_async
from langgraph.checkpoint.memory import InMemorySaver

from apps.agent.graph import Deps, build_graph
from apps.agent.schemas import (
    AltQueryOutput,
    FilmWriting,
    FiltersLM,
    JudgeOutput,
    RequestLM,
    SelectOutput,
    UnderstandOutput,
    Verdict,
    WriteOutput,
)
from apps.agent.services.llm import LLMError, LLMRefused
from apps.agent.services.locks import chat_locks
from apps.agent.services.retrieval import RetrievalResult, RetrievedCandidate
from apps.agent.services.turns import start_turn
from apps.agent.streaming import parse_sse, stream_turn
from apps.curation.tests.base import PLOT_QUOTE

INVENTED_QUOTE = "Nobody ever found the hidden bunker that lies beneath the frozen town."


def request_lm(**overrides) -> RequestLM:
    fields = {
        "en_query": "slow crime stories set in snowy small towns",
        "hyde": "A detective investigates a disappearance in a snowbound town.",
        "titles": [],
        "filters": FiltersLM(
            year_min=None, year_max=None, countries=["Finland"], max_vote_count=None
        ),
        "genres": [],
        "target_count": 5,
        "target_delta": None,
        "rank_by": None,
        "theme_present": True,
    }
    fields.update(overrides)
    return RequestLM(**fields)


def understood(
    intent="new_search", request=None, instruction="", film_id=None, people=(), keep_draft=False
):
    if request is None and intent in ("new_search", "refine"):
        request = request_lm()
    return UnderstandOutput(
        intent=intent,
        people=list(people),
        request=request,
        instruction=instruction,
        film_id=film_id,
        keep_draft=keep_draft,
    )


@dataclass
class Call:
    step: str
    user: str
    effort: str


@dataclass
class FakeLLM:
    """`fit_ids`: uygun sayılacak filmler (None = hepsi). `bad_quote_ids`: alıntısı her zaman
    uydurma olan filmler; `first_bad_ids`: yalnız ilk denemede uydurma olanlar."""

    understand: object = None
    fit_ids: set | None = None
    partial_ids: set = field(default_factory=set)
    bad_quote_ids: set = field(default_factory=set)
    first_bad_ids: set = field(default_factory=set)
    select_override: list | None = None
    fail_step: str | None = None
    refused_write_ids: set = field(
        default_factory=set
    )  # bu filmi içeren gerekçe çağrısı reddedilir
    refused_judge_ids: set = field(default_factory=set)  # bu adayı içeren değerlendirme reddedilir
    block_step: str | None = None
    reply: str = "Seçki **hazır**. Karlı kasabalar ortak nokta."
    replies: list | None = None  # doluysa her cevap çağrısı sırayla bunlardan birini verir
    calls: list = field(default_factory=list)
    gate: asyncio.Event = field(default_factory=asyncio.Event)
    started: asyncio.Event = field(default_factory=asyncio.Event)

    def steps(self, step: str) -> list[Call]:
        return [call for call in self.calls if call.step == step]

    async def structured(self, *, step, system, user, output, effort, max_tokens):
        self.calls.append(Call(step, user, effort))
        if self.fail_step == step:
            raise LLMError("Dil modeline şu an ulaşılamıyor. Biraz sonra tekrar dene.")
        if self.block_step == step:
            self.started.set()
            await self.gate.wait()
        refused = {"write": self.refused_write_ids, "judge": self.refused_judge_ids}.get(step)
        if refused and refused & set(map(int, re.findall(r'<film id="(\d+)">', user))):
            raise LLMRefused(reason="PROHIBITED_CONTENT")
        return getattr(self, f"_{step}")(user)

    async def stream_text(self, *, step, system, user, effort, max_tokens):
        self.calls.append(Call(step, user, effort))
        if self.fail_step == step:
            raise LLMError("Dil modeline şu an ulaşılamıyor. Biraz sonra tekrar dene.")
        reply = self.replies.pop(0) if self.replies else self.reply
        for word in reply.split(" "):
            yield word + " "
            await asyncio.sleep(0)

    def _parse(self, user):
        value = self.understand
        if callable(value):
            return value(user)
        return value or understood()

    def _judge(self, user):
        verdicts = []
        for film_id in map(int, re.findall(r'<film id="(\d+)">', user)):
            if self.fit_ids is None or film_id in self.fit_ids:
                verdict = "fit"
            elif film_id in self.partial_ids:
                verdict = "partial"
            else:
                verdict = "no"
            verdicts.append(Verdict(film_id=film_id, verdict=verdict, reason="Gerekçe."))
        return JudgeOutput(verdicts=verdicts)

    def _select(self, user):
        ids = list(map(int, re.findall(r'<film id="(\d+)">', user)))
        target = int(re.search(r"target_count: (\d+)", user).group(1))
        chosen = self.select_override if self.select_override is not None else ids[:target]
        return SelectOutput(
            selected_ids=chosen,
            title="Karlı kasabalarda cinayet",
            description="Yavaş tempolu kuzey polisiyeleri.",
            suggestions=["Daha karanlık olsun", "Daha eski filmler", "Sadece Avrupa"],
        )

    def _write(self, user):
        repairing = "<problems>" in user
        films = []
        for match in re.finditer(r'<film id="(\d+)">(.*?)</film>', user, re.DOTALL):
            film_id = int(match.group(1))
            plot = re.search(r'<source kind="plot">(.*?)</source>', match.group(2), re.DOTALL)
            quote = PLOT_QUOTE if plot and PLOT_QUOTE in plot.group(1) else INVENTED_QUOTE
            if film_id in self.bad_quote_ids or (film_id in self.first_bad_ids and not repairing):
                quote = INVENTED_QUOTE
            films.append(
                FilmWriting(
                    film_id=film_id,
                    rationale=f"{film_id} numaralı film kasvetli bir kış polisiyesidir.",
                    source_kind="plot",
                    source_quote=quote,
                )
            )
        return WriteOutput(films=films)

    def _retry(self, user):
        attempt = len(self.steps("retry"))
        return AltQueryOutput(
            en_query=f"alternative search number {attempt}", hyde="Another story about snow."
        )


class FakeRetrieval:
    """Her `search` çağrısı için sıradaki sonuç kullanılır (sonuncusu tekrarlanır).

    `people_found`: arama sonucunda dönen kişi sayıları; `rank_values`: film -> `rank_by` değeri;
    `sources`: film -> kaynak adları (yoksa "dense"); `people_index`: ad -> film kimlikleri
    (`people_films` için)."""

    def __init__(
        self, *results, people_found=(), rank_values=None, sources=None, people_index=None
    ):
        self.results = results or ([],)
        self.calls: list[dict] = []
        self.people_found = tuple(people_found)
        self.rank_values = rank_values or {}
        self.sources = sources or {}
        self.people_index = people_index or {}
        self.people_calls: list[list] = []

    async def search(self, request, *, limit, exclude_film_ids=()):
        self.calls.append({"request": request, "limit": limit, "exclude": tuple(exclude_film_ids)})
        spec = self.results[min(len(self.calls), len(self.results)) - 1]
        ids, relaxed = spec if isinstance(spec, tuple) else (spec, ())
        ids = [film_id for film_id in ids if film_id not in set(exclude_film_ids)]
        candidates = tuple(
            RetrievedCandidate(
                film_id,
                1.0 - rank / 100,
                rank,
                tuple(self.sources.get(film_id, ("dense",))),
                self.rank_values.get(film_id),
            )
            for rank, film_id in enumerate(ids, start=1)
        )
        return RetrievalResult(
            candidates, tuple(relaxed), len(candidates), {"search": 0.01}, self.people_found
        )

    async def people_films(self, people):
        self.people_calls.append(list(people))
        result = []
        for name, _role in people:
            film_ids = list(self.people_index.get(name, ()))
            result.append((name, len(film_ids), film_ids))
        return result


def make_graph(llm, retrieval, saver=None):
    return build_graph(Deps(llm=llm, retrieval=retrieval), saver or InMemorySaver())


async def run_turn(graph, chat, user, text, action=None):
    """Görünümün yaptığı işi (kilit, kullanıcı mesajı, kimlik ayırma, akış) tek çağrıda yapar."""
    token = chat_locks.try_acquire(chat.pk)
    user_message, message_id = await sync_to_async(start_turn)(chat, text, action)
    chunks = []
    async for chunk in stream_turn(
        graph,
        chat_id=chat.pk,
        user_id=user.pk,
        thread_id=str(chat.thread_id),
        user_message=user_message,
        message_id=message_id,
        text=text,
        action=action,
        lock_token=token,
    ):
        chunks.append(chunk)
    return parse_sse("".join(chunks))


def names(events) -> list[str]:
    return [name for name, _ in events]


def data_of(events, name) -> list[dict]:
    return [data for event, data in events if event == name]
