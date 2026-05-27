"""
tests/test_resolver.py

Unit tests for PokemonResolver.

Uses the same in-memory test database pattern as test_pokemon.py so tests
are fully self-contained and deterministic.
"""

from pokedex_rsa.models.resolver import (
    PokemonResolver,
    NoMatchError,
    AmbiguousMatchError,
)
import sqlite3
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Shared test database fixture
# ---------------------------------------------------------------------------

SCHEMA = """
    CREATE TABLE pokemon (
        id              INTEGER NOT NULL,
        form            TEXT    NOT NULL DEFAULT 'default',
        name            TEXT    NOT NULL UNIQUE,
        type_primary    TEXT    NOT NULL,
        type_secondary  TEXT,
        height          REAL    NOT NULL,
        weight          REAL    NOT NULL,
        base_stat_total INTEGER NOT NULL,
        generation      INTEGER NOT NULL,
        color           TEXT    NOT NULL,
        PRIMARY KEY (id, form)
    )
"""

TEST_RECORDS = [
    (1,   "default", "bulbasaur",        "grass",
     "poison", 0.7,  6.9,  318, 1, "green"),
    (4,   "default", "charmander",       "fire",
     None,     0.6,  8.5,  309, 1, "red"),
    (7,   "default", "squirtle",         "water",
     None,     0.5,  9.0,  314, 1, "blue"),
    (155, "default", "cyndaquil",        "fire",
     None,     0.5,  7.9,  309, 2, "yellow"),
    (157, "default", "typhlosion",       "fire",
     None,     1.75, 79.5, 534, 2, "yellow"),
    (157, "hisui",   "typhlosion-hisui", "fire",
     "ghost",  1.75, 79.5, 534, 2, "yellow"),
    (258, "default", "mudkip",           "water",
     None,     0.4,  7.6,  310, 3, "blue"),
]


@pytest.fixture
def resolver(tmp_path):
    """
    PokemonResolver pointed at a temporary SQLite file pre-loaded with
    TEST_RECORDS.
    """
    db_file = tmp_path / "test_pokemon.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute(SCHEMA)
    conn.executemany(
        "INSERT INTO pokemon VALUES (?,?,?,?,?,?,?,?,?,?)",
        TEST_RECORDS
    )
    conn.commit()
    conn.close()

    return PokemonResolver(db_path=str(db_file))


# ---------------------------------------------------------------------------
# resolve() — success cases
# ---------------------------------------------------------------------------

class TestResolveSuccess:

    def test_resolves_unique_bundle(self, resolver):
        # Only one grass/poison Pokemon in the test DB
        result = resolver.resolve(
            {"type_primary": "grass", "type_secondary": "poison"})
        assert result.name == "bulbasaur"

    def test_resolves_by_multiple_fields(self, resolver):
        # Charmander is the only fire-type Gen 1 Pokemon
        result = resolver.resolve({"type_primary": "fire", "generation": 1})
        assert result.name == "charmander"

    def test_resolves_regional_variant(self, resolver):
        # Hisuian Typhlosion is the only fire/ghost Pokemon
        result = resolver.resolve(
            {"type_primary": "fire", "type_secondary": "ghost"})
        assert result.name == "typhlosion-hisui"
        assert result.form == "hisui"

    def test_resolves_by_form_field(self, resolver):
        result = resolver.resolve({"id": 157, "form": "hisui"})
        assert result.name == "typhlosion-hisui"

    def test_resolves_by_unique_weight(self, resolver):
        # Typhlosion (default) has weight 79.5 — unique in the test DB
        # but we need to also exclude hisui since it shares weight
        result = resolver.resolve({"weight": 79.5, "form": "default"})
        assert result.name == "typhlosion"

    def test_resolved_pokemon_is_correct_type(self, resolver):
        result = resolver.resolve({"type_primary": "grass"})
        assert result.type_primary == "grass"


# ---------------------------------------------------------------------------
# resolve() — failure cases
# ---------------------------------------------------------------------------

class TestResolveFailures:

    def test_raises_no_match_error(self, resolver):
        with pytest.raises(NoMatchError) as exc_info:
            resolver.resolve({"type_primary": "dragon"})
        assert "dragon" in str(exc_info.value)

    def test_no_match_error_carries_bundle(self, resolver):
        bundle = {"type_primary": "dragon"}
        with pytest.raises(NoMatchError) as exc_info:
            resolver.resolve(bundle)
        assert exc_info.value.bundle == bundle

    def test_raises_ambiguous_match_error(self, resolver):
        # "fire" alone matches charmander, cyndaquil, typhlosion, typhlosion-hisui
        with pytest.raises(AmbiguousMatchError) as exc_info:
            resolver.resolve({"type_primary": "fire"})
        assert len(exc_info.value.matches) > 1

    def test_ambiguous_error_carries_matches(self, resolver):
        with pytest.raises(AmbiguousMatchError) as exc_info:
            resolver.resolve({"type_primary": "fire"})
        match_names = {p.name for p in exc_info.value.matches}
        assert "charmander" in match_names
        assert "cyndaquil" in match_names

    def test_raises_value_error_on_invalid_field(self, resolver):
        with pytest.raises(ValueError):
            resolver.resolve({"not_a_field": "value"})


# ---------------------------------------------------------------------------
# candidates()
# ---------------------------------------------------------------------------

class TestCandidates:

    def test_returns_all_matches(self, resolver):
        results = resolver.candidates({"type_primary": "fire"})
        # charmander, cyndaquil, typhlosion, typhlosion-hisui
        assert len(results) == 4

    def test_returns_empty_list_for_no_match(self, resolver):
        results = resolver.candidates({"type_primary": "dragon"})
        assert results == []

    def test_returns_one_for_unique_bundle(self, resolver):
        results = resolver.candidates({"type_primary": "grass"})
        assert len(results) == 1


# ---------------------------------------------------------------------------
# is_unique()
# ---------------------------------------------------------------------------

class TestIsUnique:

    def test_true_for_unique_bundle(self, resolver):
        assert resolver.is_unique({"type_primary": "grass"}) is True

    def test_false_for_ambiguous_bundle(self, resolver):
        assert resolver.is_unique({"type_primary": "fire"}) is False

    def test_false_for_no_match(self, resolver):
        assert resolver.is_unique({"type_primary": "dragon"}) is False


# ---------------------------------------------------------------------------
# suggest_disambiguating_fields()
# ---------------------------------------------------------------------------

class TestSuggestDisambiguatingFields:

    def test_suggests_fields_that_differ(self, resolver):
        bundle = {"type_primary": "fire", "generation": 2}
        # Gen 2 fire types: cyndaquil (BST 309) and typhlosion (BST 534)
        # and typhlosion-hisui (BST 534, form=hisui)
        matches = resolver.candidates(bundle)
        suggestions = resolver.suggest_disambiguating_fields(bundle, matches)
        # base_stat_total differs across these three, so it should be suggested
        assert "base_stat_total" in suggestions

    def test_does_not_suggest_already_used_fields(self, resolver):
        bundle = {"type_primary": "fire"}
        matches = resolver.candidates(bundle)
        suggestions = resolver.suggest_disambiguating_fields(bundle, matches)
        assert "type_primary" not in suggestions

    def test_returns_empty_for_single_match(self, resolver):
        bundle = {"type_primary": "grass"}
        matches = resolver.candidates(bundle)
        suggestions = resolver.suggest_disambiguating_fields(bundle, matches)
        assert suggestions == []

    def test_returns_empty_for_no_matches(self, resolver):
        bundle = {"type_primary": "dragon"}
        suggestions = resolver.suggest_disambiguating_fields(bundle, [])
        assert suggestions == []
