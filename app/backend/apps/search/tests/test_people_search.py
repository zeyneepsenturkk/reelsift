from pathlib import Path

from django.test import TestCase

from apps.search.services import lexical, pipeline
from apps.search.services.types import ParsedQuery, PersonHint, QueryFilters, TitleHint
from apps.search.tests.base import fake_models, make_film, search_settings

LYNCH = "David Lynch"
PRIOR = {"rating_prior_votes": 200, "rating_prior_mean": 6.0}


class PeopleSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.velvet = make_film(
            "L1",
            title="Blue Velvet",
            year=1986,
            directors=(LYNCH,),
            actors=("Isabella Rossellini",),
            vote_average=8.0,
            vote_count=800,
        )
        cls.gem = make_film(
            "L2",
            title="Obscure Gem",
            year=2001,
            directors=(LYNCH,),
            vote_average=9.5,
            vote_count=50,
        )
        # Hikâyesi 300 karakterden kısa: kişi evreninde elenmez.
        cls.short = make_film(
            "L3",
            title="Short Lynch",
            year=1999,
            plot="A dream.",
            directors=("DAVID LYNCH",),
            vote_average=7.0,
            vote_count=400,
        )
        cls.cameo = make_film(
            "L4", title="Cameo Dream", year=2010, directors=("Someone Else",), actors=(LYNCH,)
        )
        cls.decoy = make_film(
            "L5", title="Lynch Documentary Dream", year=2005, directors=("Peter Lynch",)
        )
        cls.zeki = make_film(
            "Z1",
            title="Destiny",
            original_title="Kader",
            year=2006,
            directors=("Zeki Demirkubuz",),
            vote_average=7.4,
            vote_count=122,
        )
        cls.other = make_film("O1", title="Plain Dream", year=2012, directors=("Nobody",))
        # Derleme: 4 yönetmen (ayarda en çok 3). Biri aynı zamanda oyuncu.
        cls.anthology = make_film(
            "A1",
            title="Omnibus Dream",
            year=1995,
            directors=("Omnibus Director", "Second", "Third", "Fourth"),
            actors=("Omnibus Director",),
        )
        cls.film_ids = {
            cls.velvet.pk: "velvet",
            cls.gem.pk: "gem",
            cls.short.pk: "short",
            cls.cameo.pk: "cameo",
            cls.zeki.pk: "zeki",
        }

    def run_search(self, query, **kwargs):
        overrides = kwargs.pop("settings", {})
        with search_settings(**{**PRIOR, **overrides}), fake_models():
            return pipeline.search(query, **kwargs)

    def person_query(self, *people, **kwargs):
        return ParsedQuery(
            "films directed by someone", "a dream story", people=tuple(people), **kwargs
        )

    def ids(self, result):
        return [candidate.film_id for candidate in result.candidates]

    def test_only_the_named_directors_films_are_candidates(self):
        result = self.run_search(self.person_query(PersonHint(LYNCH, "director")))

        self.assertEqual(
            set(self.ids(result)), {self.velvet.pk, self.gem.pk, self.short.pk}
        )  # başka yönetmenin filmi, adı geçen belgesel ve oyuncu olduğu film gelmez
        self.assertEqual(result.people_found, ((LYNCH, 3),))
        for candidate in result.candidates:
            self.assertIn("person", candidate.sources)

    def test_anthology_with_too_many_directors_is_not_a_directors_film(self):
        as_director = self.run_search(self.person_query(PersonHint("Omnibus Director", "director")))
        as_actor = self.run_search(self.person_query(PersonHint("Omnibus Director", "actor")))
        as_any = self.run_search(self.person_query(PersonHint("Second", "any")))

        self.assertEqual(as_director.candidates, ())
        self.assertEqual(as_director.people_found, (("Omnibus Director", 0),))
        self.assertEqual(self.ids(as_actor), [self.anthology.pk])  # oyunculuk yoluyla girer
        self.assertEqual(as_any.people_found, (("Second", 0),))  # yalnız yönetmen: girmez

    def test_short_story_film_is_not_dropped_in_the_person_universe(self):
        result = self.run_search(self.person_query(PersonHint(LYNCH, "director")))

        self.assertIn(self.short.pk, self.ids(result))

    def test_role_decides_which_films_belong_to_the_person(self):
        actor = self.run_search(self.person_query(PersonHint(LYNCH, "actor")))
        anyone = self.run_search(self.person_query(PersonHint(LYNCH, "any")))

        self.assertEqual(self.ids(actor), [self.cameo.pk])
        self.assertEqual(actor.people_found, ((LYNCH, 1),))
        self.assertEqual(
            set(self.ids(anyone)), {self.velvet.pk, self.gem.pk, self.short.pk, self.cameo.pk}
        )
        self.assertEqual(anyone.people_found, ((LYNCH, 4),))

    def test_several_people_give_the_union(self):
        query = self.person_query(PersonHint(LYNCH, "director"), PersonHint("zeki demirkubuz"))

        result = self.run_search(query)

        self.assertEqual(
            set(self.ids(result)), {self.velvet.pk, self.gem.pk, self.short.pk, self.zeki.pk}
        )
        self.assertEqual(result.people_found, ((LYNCH, 3), ("zeki demirkubuz", 1)))

    def test_unknown_person_gives_an_empty_result_and_zero_count(self):
        result = self.run_search(self.person_query(PersonHint("Uydurma Kişi", "director")))

        self.assertEqual(result.candidates, ())
        self.assertEqual(result.pool_size, 0)
        self.assertEqual(result.people_found, (("Uydurma Kişi", 0),))

    def test_a_surname_alone_does_not_find_anybody(self):
        result = self.run_search(self.person_query(PersonHint("Lynch", "any")))

        self.assertEqual(result.candidates, ())
        self.assertEqual(result.people_found, (("Lynch", 0),))

    def test_one_unknown_person_does_not_widen_the_known_ones(self):
        query = self.person_query(PersonHint("Uydurma Kişi"), PersonHint("Zeki Demirkubuz"))

        result = self.run_search(query)

        self.assertEqual(self.ids(result), [self.zeki.pk])
        self.assertEqual(result.people_found, (("Uydurma Kişi", 0), ("Zeki Demirkubuz", 1)))

    def test_filters_apply_inside_the_universe_without_the_thirty_film_rule(self):
        query = self.person_query(
            PersonHint(LYNCH, "director"), filters=QueryFilters(year_min=1990)
        )

        result = self.run_search(query)

        self.assertEqual(set(self.ids(result)), {self.gem.pk, self.short.pk})
        self.assertEqual(result.relaxed_filters, ())

    def test_filter_that_empties_the_universe_is_dropped_and_reported(self):
        query = self.person_query(
            PersonHint(LYNCH, "director"), filters=QueryFilters(year_min=2020, countries=("X",))
        )

        result = self.run_search(query)

        self.assertEqual(set(self.ids(result)), {self.velvet.pk, self.gem.pk, self.short.pk})
        self.assertEqual(result.relaxed_filters, ("year_min", "countries"))

    def test_excluded_films_stay_out_and_exclusion_is_never_relaxed(self):
        query = self.person_query(PersonHint(LYNCH, "director"))

        partly = self.run_search(query, exclude_film_ids=[self.velvet.pk])
        fully = self.run_search(
            query, exclude_film_ids=[self.velvet.pk, self.gem.pk, self.short.pk]
        )

        self.assertEqual(set(self.ids(partly)), {self.gem.pk, self.short.pk})
        self.assertEqual(fully.candidates, ())
        self.assertEqual(fully.people_found, ((LYNCH, 3),))

    def test_limit_caps_the_universe(self):
        result = self.run_search(self.person_query(PersonHint(LYNCH, "director")), limit=2)

        self.assertEqual(len(result.candidates), 2)
        self.assertEqual(result.people_found, ((LYNCH, 3),))

    def test_without_people_nothing_changes(self):
        plain = self.run_search(ParsedQuery("dream", "a dream story"))

        self.assertEqual(plain.people_found, ())
        self.assertTrue(all(c.rank_value is None for c in plain.candidates))
        self.assertTrue(all("person" not in c.sources for c in plain.candidates))
        self.assertNotIn(self.short.pk, self.ids(plain))  # 300 karakter kuralı yerinde

    def test_rating_order_uses_the_weighted_average_not_the_raw_one(self):
        query = self.person_query(PersonHint(LYNCH, "director"), rank_by="rating")

        result = self.run_search(query)

        # velvet (8.0, 800 oy) = 0.8*8.0 + 0.2*6.0 = 7.6
        # gem (9.5, 50 oy) = 0.2*9.5 + 0.8*6.0 = 6.7
        # short (7.0, 400 oy) = (2/3)*7.0 + (1/3)*6.0 = 6.667. Ham ortalamada gem birinci olurdu.
        self.assertEqual(self.ids(result), [self.velvet.pk, self.gem.pk, self.short.pk])
        values = [candidate.rank_value for candidate in result.candidates]
        self.assertAlmostEqual(values[0], 7.6)
        self.assertAlmostEqual(values[1], 6.7)
        self.assertAlmostEqual(values[2], 6.0 + 2 / 3)

    def test_rating_order_does_not_follow_the_rerank_scores(self):
        def prefer_the_gem(pairs):
            return [100.0 if "Obscure" in document else 1.0 for _, document in pairs]

        query = self.person_query(PersonHint(LYNCH, "director"), rank_by="rating")
        with search_settings(**PRIOR), fake_models(score_pairs=prefer_the_gem):
            result = pipeline.search(query)

        self.assertEqual(result.candidates[0].film_id, self.velvet.pk)
        self.assertEqual(result.candidates[1].rerank_score, 1.0)  # puan hesaplanır ve taşınır

    def test_rating_cut_comes_from_the_whole_universe_not_the_first_page(self):
        query = self.person_query(PersonHint(LYNCH, "director"), rank_by="rating")

        result = self.run_search(query, limit=2)

        self.assertEqual(self.ids(result), [self.velvet.pk, self.gem.pk])

    def test_popularity_order_is_by_vote_count(self):
        query = self.person_query(PersonHint(LYNCH, "director"), rank_by="popularity")

        result = self.run_search(query)

        self.assertEqual(self.ids(result), [self.velvet.pk, self.short.pk, self.gem.pk])
        self.assertEqual(result.candidates[0].rank_value, 800.0)

    def test_rank_by_without_people_only_carries_the_value(self):
        base = self.run_search(ParsedQuery("dream", "a dream story"))
        ranked = self.run_search(ParsedQuery("dream", "a dream story", rank_by="rating"))

        self.assertEqual(self.ids(ranked), self.ids(base))
        self.assertTrue(all(c.rank_value is not None for c in ranked.candidates))

    def test_original_and_turkish_titles_match_model_suggestions(self):
        suggested = ParsedQuery("dream", "a dream", titles=(TitleHint("Kader", 2006),))

        result = self.run_search(suggested)

        by_film = {c.film_id: c for c in result.candidates}
        self.assertIn("g", by_film[self.zeki.pk].sources)  # özgün adı "Kader", `title` "Destiny"


class IndexFilesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.film = make_film(
            "T1",
            title="Destiny",
            original_title="Kader",
            tr_title="Kader (Türkçe)",
            directors=("Zeki Demirkubuz",),
        )
        cls.same = make_film("T2", title="Heat", original_title="HEAT")

    def test_title_index_has_title_original_and_turkish_keys_without_duplicates(self):
        with search_settings():
            index = lexical.get_index()

        self.assertEqual(index.titles["destiny"], [(self.film.pk, 2000)])
        self.assertEqual(index.titles["kader"], [(self.film.pk, 2000)])
        self.assertEqual(index.titles["kader turkce"], [(self.film.pk, 2000)])
        self.assertEqual(index.titles["heat"], [(self.same.pk, 2000)])  # özgün ad aynı: tek satır

    def test_person_index_is_built_saved_and_loaded_with_the_index(self):
        with search_settings() as directory:
            summary = lexical.build_index()
            self.assertIn("kisiler", summary["seconds"])
            base = Path(directory) / "lexical"
            self.assertTrue((base / "people.json").exists())
            self.assertTrue((base / "people.npz").exists())
            lexical.reset_loaded()
            index = lexical.get_index()

        self.assertEqual(index.people.films("Zeki Demirkubuz", "director").tolist(), [self.film.pk])

    def test_index_without_the_person_files_counts_as_missing_and_is_rebuilt(self):
        with search_settings() as directory:
            lexical.build_index()
            (Path(directory) / "lexical" / "people.json").unlink()
            lexical.reset_loaded()

            self.assertFalse(lexical.index_exists())
            index = lexical.get_index()

            self.assertTrue(lexical.index_exists())
            self.assertEqual(index.people.films("Zeki Demirkubuz", "any").tolist(), [self.film.pk])
