"""
tests/test_pokemon.py

Unit tests for the Pokemon dataclass and PokemonDB access layer.

These tests run against a small in-memory SQLite database seeded with
a handful of known records, so they do not require the real pokemon.db
to be present and produce fully deterministic results.
"""

from pokedex_rsa.models.pokemon import Pokemon, PokemonDB, DEFAULT_DB_PATH
import sqlite3
import os
import sys
import pytest

# Allow imports from the project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# In-memory test database fixture
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

# A small deterministic set covering:
#   - single and dual types
#   - a regional variant (same id, different form)
#   - multiple generations
TEST_RECORDS = [
    (1,   "default", "bulbasaur",       "grass",
     "poison", 0.7,  6.9,  318, 1, "green"),
    (4,   "default", "charmander",      "fire",
     None,     0.6,  8.5,  309, 1, "red"),
    (7,   "default", "squirtle",        "water",
     None,     0.5,  9.0,  314, 1, "blue"),
    (155, "default", "cyndaquil",       "fire",
     None,     0.5,  7.9,  309, 2, "yellow"),
    (157, "default", "typhlosion",      "fire",
     None,     1.75, 79.5, 534, 2, "yellow"),
    (157, "hisui",   "typhlosion-hisui", "fire",
     "ghost",  1.75, 79.5, 534, 2, "yellow"),
    (258, "default", "mudkip",          "water",
     None,     0.4,  7.6,  310, 3, "blue"),
]


@pytest.fixture
def db(tmp_path):
    """
    PokemonDB instance pointed at a temporary SQLite file pre-loaded with
    TEST_RECORDS. Yields an open db; closes automatically after the test.
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

    pdb = PokemonDB(db_path=str(db_file))
    pdb.open()
    yield pdb
    pdb.close()


# ---------------------------------------------------------------------------
# Pokemon dataclass
# ---------------------------------------------------------------------------

class TestPokemonDataclass:

    def test_single_type_types_property(self):
        p = Pokemon(4, "default", "charmander", "fire",
                    None, 0.6, 8.5, 309, 1, "red")
        assert p.types == ("fire",)

    def test_dual_type_types_property(self):
        p = Pokemon(1, "default", "bulbasaur", "grass",
                    "poison", 0.7, 6.9, 318, 1, "green")
        assert p.types == ("grass", "poison")

    def test_is_default_form_true(self):
        p = Pokemon(4, "default", "charmander", "fire",
                    None, 0.6, 8.5, 309, 1, "red")
        assert p.is_default_form is True

    def test_is_default_form_false(self):
        p = Pokemon(157, "hisui", "typhlosion-hisui", "fire",
                    "ghost", 1.75, 79.5, 534, 2, "yellow")
        assert p.is_default_form is False

    def test_frozen(self):
        p = Pokemon(4, "default", "charmander", "fire",
                    None, 0.6, 8.5, 309, 1, "red")
        with pytest.raises(Exception):
            p.name = "pikachu"  # type: ignore

    def test_str_default_form(self):
        p = Pokemon(4, "default", "charmander", "fire",
                    None, 0.6, 8.5, 309, 1, "red")
        result = str(p)
        assert "charmander" in result.lower()
        assert "fire" in result
        assert "309" in result

    def test_str_variant_includes_form(self):
        p = Pokemon(157, "hisui", "typhlosion-hisui", "fire",
                    "ghost", 1.75, 79.5, 534, 2, "yellow")
        result = str(p)
        assert "hisui" in result.lower()


# ---------------------------------------------------------------------------
# PokemonDB — connection management
# ---------------------------------------------------------------------------

class TestPokemonDBConnection:

    def test_context_manager(self, tmp_path):
        db_file = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute(SCHEMA)
        conn.commit()
        conn.close()

        with PokemonDB(db_path=str(db_file)) as pdb:
            assert pdb.count() == 0

    def test_raises_if_db_missing(self, tmp_path):
        pdb = PokemonDB(db_path=str(tmp_path / "nonexistent.db"))
        with pytest.raises(FileNotFoundError):
            pdb.open()

    def test_raises_if_not_open(self, tmp_path):
        db_file = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute(SCHEMA)
        conn.commit()
        conn.close()

        pdb = PokemonDB(db_path=str(db_file))
        with pytest.raises(RuntimeError):
            _ = pdb.conn


# ---------------------------------------------------------------------------
# PokemonDB — queries
# ---------------------------------------------------------------------------

class TestPokemonDBQueries:

    def test_count(self, db):
        assert db.count() == len(TEST_RECORDS)

    def test_get_default_form(self, db):
        p = db.get(4)
        assert p is not None
        assert p.name == "charmander"
        assert p.form == "default"

    def test_get_variant_form(self, db):
        p = db.get(157, form="hisui")
        assert p is not None
        assert p.name == "typhlosion-hisui"
        assert p.type_secondary == "ghost"

    def test_get_returns_none_for_missing(self, db):
        assert db.get(9999) is None

    def test_get_by_name(self, db):
        p = db.get_by_name("bulbasaur")
        assert p is not None
        assert p.id == 1

    def test_get_by_name_variant(self, db):
        p = db.get_by_name("typhlosion-hisui")
        assert p is not None
        assert p.form == "hisui"

    def test_get_by_name_returns_none_for_missing(self, db):
        assert db.get_by_name("missingno") is None

    def test_all_returns_all_records(self, db):
        results = db.all()
        assert len(results) == len(TEST_RECORDS)

    def test_all_ordered_by_id_then_form(self, db):
        results = db.all()
        # Both Typhlosion forms should be adjacent, default before hisui
        typhlosions = [p for p in results if p.id == 157]
        assert len(typhlosions) == 2
        assert typhlosions[0].form == "default"
        assert typhlosions[1].form == "hisui"

    def test_find_by_single_field(self, db):
        results = db.find_by(type_primary="fire")
        names = {p.name for p in results}
        assert "charmander" in names
        assert "cyndaquil" in names
        assert "typhlosion" in names
        assert "typhlosion-hisui" in names  # fire/ghost is still fire primary
        assert "bulbasaur" not in names

    def test_find_by_multiple_fields(self, db):
        results = db.find_by(type_primary="fire", generation=1)
        assert len(results) == 1
        assert results[0].name == "charmander"

    def test_find_by_null_field(self, db):
        results = db.find_by(type_secondary=None)
        names = {p.name for p in results}
        assert "bulbasaur" not in names     # has type_secondary=poison
        assert "charmander" in names        # no secondary
        assert "typhlosion-hisui" not in names  # has type_secondary=ghost

    def test_find_by_returns_empty_list_for_no_match(self, db):
        results = db.find_by(type_primary="dragon")
        assert results == []

    def test_find_by_raises_on_invalid_field(self, db):
        with pytest.raises(ValueError):
            db.find_by(not_a_real_field="value")

    def test_find_by_no_args_returns_all(self, db):
        assert len(db.find_by()) == len(TEST_RECORDS)

    def test_generations(self, db):
        assert db.generations() == [1, 2, 3]
