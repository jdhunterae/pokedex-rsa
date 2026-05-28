"""
tests/test_encryption_controller.py

End-to-end tests for EncryptionController.

Tests cover:
  - Exact bundle keygen (original behavior)
  - Partial bundle keygen (random from pool)
  - No bundle keygen (fully random)
  - Auto-bundle construction
  - count_candidates and random_pokemon helpers
  - Encrypt, decrypt, full pipeline round-trips
  - JSON serialization
  - validate_bundle helper
  - Error cases

Uses an in-memory SQLite fixture so tests are fully self-contained.
"""

from pokedex_rsa.models.crypto import derive_prime, generate_keypair
from pokedex_rsa.controllers.encryption_controller import (
    EncryptionController,
    PokedexPublicBundle,
    PokedexKeypair,
    EncryptedMessage,
    ResolutionError,
    SamePokemonError,
    EmptyDatabaseError,
)
import copy
import sqlite3
import json
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

# Exact bundles (resolve to exactly one Pokemon)
BUNDLE_BULBASAUR = {"type_primary": "grass"}
BUNDLE_CHARMANDER = {"type_primary": "fire", "generation": 1}
BUNDLE_SQUIRTLE = {"type_primary": "water", "generation": 1}
BUNDLE_CYNDAQUIL = {"type_primary": "fire", "weight": 7.9}
BUNDLE_TYPHLOSION = {"type_primary": "fire",
                     "base_stat_total": 534, "form": "default"}
BUNDLE_HISUI = {"type_primary": "fire", "type_secondary": "ghost"}
BUNDLE_MUDKIP = {"type_primary": "water", "generation": 3}

# Partial bundle (matches multiple Pokemon — valid for restricted random)
BUNDLE_PARTIAL_FIRE = {"type_primary": "fire"}   # 4 matches

# No-match bundle
BUNDLE_NO_MATCH = {"type_primary": "dragon"}


@pytest.fixture
def controller(tmp_path):
    db_file = tmp_path / "test_pokemon.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute(SCHEMA)
    conn.executemany(
        "INSERT INTO pokemon VALUES (?,?,?,?,?,?,?,?,?,?)", TEST_RECORDS)
    conn.commit()
    conn.close()
    return EncryptionController(db_path=str(db_file))


@pytest.fixture
def empty_controller(tmp_path):
    """Controller pointing at an empty (schema-only) database."""
    db_file = tmp_path / "empty.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute(SCHEMA)
    conn.commit()
    conn.close()
    return EncryptionController(db_path=str(db_file))


# ---------------------------------------------------------------------------
# generate_keypair — exact bundle (original behavior)
# ---------------------------------------------------------------------------

class TestGenerateKeypairExact:

    def test_returns_pokedex_keypair(self, controller):
        kp = controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_CHARMANDER)
        assert isinstance(kp, PokedexKeypair)

    def test_exact_bundle_selects_correct_pokemon(self, controller):
        kp = controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_CHARMANDER)
        assert kp.pokemon_p.name == "bulbasaur"
        assert kp.pokemon_q.name == "charmander"

    def test_public_bundle_uniquely_resolves(self, controller):
        # Auto-constructed bundles must still resolve correctly
        kp = controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_CHARMANDER)
        ok_p, _, p = controller.validate_bundle(kp.public_bundle.bundle_p)
        ok_q, _, q = controller.validate_bundle(kp.public_bundle.bundle_q)
        assert ok_p and p.name == "bulbasaur"
        assert ok_q and q.name == "charmander"

    def test_rsa_keys_are_valid(self, controller):
        kp = controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_CHARMANDER)
        assert kp.public_key.n > 0
        assert kp.public_key.e == 65537
        assert kp.private_key.n == kp.public_key.n

    def test_n_matches_derived_primes(self, controller):
        kp = controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_CHARMANDER)
        p = derive_prime("bulbasaur")
        q = derive_prime("charmander")
        assert kp.public_key.n == p * q

    def test_works_with_regional_variant(self, controller):
        kp = controller.generate_keypair(BUNDLE_TYPHLOSION, BUNDLE_HISUI)
        assert kp.pokemon_p.name == "typhlosion"
        assert kp.pokemon_q.name == "typhlosion-hisui"

    def test_raises_on_no_match_bundle(self, controller):
        with pytest.raises(ResolutionError):
            controller.generate_keypair(BUNDLE_NO_MATCH, BUNDLE_CHARMANDER)

    def test_raises_same_pokemon_error(self, controller):
        with pytest.raises(SamePokemonError):
            controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_BULBASAUR)

    def test_same_pokemon_error_carries_pokemon(self, controller):
        with pytest.raises(SamePokemonError) as exc_info:
            controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_BULBASAUR)
        assert exc_info.value.pokemon.name == "bulbasaur"


# ---------------------------------------------------------------------------
# generate_keypair — partial bundle (restricted random)
# ---------------------------------------------------------------------------

class TestGenerateKeypairPartial:

    def test_partial_bundle_produces_valid_keypair(self, controller):
        # fire matches 4 Pokemon — should pick one and succeed
        kp = controller.generate_keypair(BUNDLE_PARTIAL_FIRE, BUNDLE_SQUIRTLE)
        assert isinstance(kp, PokedexKeypair)

    def test_partial_bundle_p_picks_from_correct_pool(self, controller):
        kp = controller.generate_keypair(BUNDLE_PARTIAL_FIRE, BUNDLE_SQUIRTLE)
        assert kp.pokemon_p.type_primary == "fire"

    def test_partial_bundle_q_picks_from_correct_pool(self, controller):
        kp = controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_PARTIAL_FIRE)
        assert kp.pokemon_q.type_primary == "fire"

    def test_partial_both_slots_produces_valid_keypair(self, controller):
        water = {"type_primary": "water"}  # 2 matches: squirtle, mudkip
        kp = controller.generate_keypair(BUNDLE_PARTIAL_FIRE, water)
        assert isinstance(kp, PokedexKeypair)
        assert kp.pokemon_p.type_primary == "fire"
        assert kp.pokemon_q.type_primary == "water"

    def test_partial_bundle_auto_constructs_unique_public_bundle(self, controller):
        kp = controller.generate_keypair(BUNDLE_PARTIAL_FIRE, BUNDLE_SQUIRTLE)
        # Public bundle must resolve back to the same Pokemon
        ok_p, _, p = controller.validate_bundle(kp.public_bundle.bundle_p)
        assert ok_p
        assert p.name == kp.pokemon_p.name

    def test_partial_no_match_raises(self, controller):
        with pytest.raises(ResolutionError):
            controller.generate_keypair(BUNDLE_NO_MATCH, BUNDLE_SQUIRTLE)

    def test_partial_result_is_nondeterministic(self, controller):
        # Running multiple times with the same partial bundle should
        # occasionally produce different Pokemon (not guaranteed but very
        # likely with 4 candidates over 20 runs)
        names = {
            controller.generate_keypair(
                BUNDLE_PARTIAL_FIRE, BUNDLE_SQUIRTLE).pokemon_p.name
            for _ in range(20)
        }
        assert len(names) > 1, (
            "Expected random selection to produce multiple different Pokemon "
            "across 20 runs with 4 candidates."
        )


# ---------------------------------------------------------------------------
# generate_keypair — no bundle (fully random)
# ---------------------------------------------------------------------------

class TestGenerateKeypairRandom:

    def test_no_bundles_produces_valid_keypair(self, controller):
        kp = controller.generate_keypair()
        assert isinstance(kp, PokedexKeypair)

    def test_random_keypair_has_valid_rsa_keys(self, controller):
        kp = controller.generate_keypair()
        assert kp.public_key.n > 0
        assert kp.public_key.e == 65537
        assert kp.private_key.n == kp.public_key.n

    def test_random_pokemon_are_distinct(self, controller):
        kp = controller.generate_keypair()
        assert kp.pokemon_p.name != kp.pokemon_q.name

    def test_random_public_bundle_resolves_uniquely(self, controller):
        kp = controller.generate_keypair()
        ok_p, _, p = controller.validate_bundle(kp.public_bundle.bundle_p)
        ok_q, _, q = controller.validate_bundle(kp.public_bundle.bundle_q)
        assert ok_p and p.name == kp.pokemon_p.name
        assert ok_q and q.name == kp.pokemon_q.name

    def test_random_keypair_round_trips(self, controller):
        kp = controller.generate_keypair()
        msg = "Randomly generated keypair round-trip."
        em = controller.encrypt(msg, kp.public_bundle)
        assert controller.decrypt(em, kp.private_key) == msg

    def test_empty_bundle_same_as_none(self, controller):
        # {} and None should both mean "pick from entire DB"
        kp = controller.generate_keypair({}, {})
        assert isinstance(kp, PokedexKeypair)

    def test_empty_database_raises(self, empty_controller):
        # Empty DB raises ResolutionError (no candidates) rather than EmptyDatabaseError
        # since pool resolution now happens before the empty DB guard
        with pytest.raises((EmptyDatabaseError, ResolutionError)):
            empty_controller.generate_keypair()


# ---------------------------------------------------------------------------
# _build_minimal_bundle (via public bundle output)
# ---------------------------------------------------------------------------

class TestAutoBundleConstruction:

    def test_auto_bundle_is_dict(self, controller):
        kp = controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_CHARMANDER)
        assert isinstance(kp.public_bundle.bundle_p, dict)
        assert isinstance(kp.public_bundle.bundle_q, dict)

    def test_auto_bundle_is_non_empty(self, controller):
        kp = controller.generate_keypair()
        assert len(kp.public_bundle.bundle_p) > 0
        assert len(kp.public_bundle.bundle_q) > 0

    def test_auto_bundle_resolves_to_correct_pokemon(self, controller):
        for _ in range(5):
            kp = controller.generate_keypair()
            ok_p, _, p = controller.validate_bundle(kp.public_bundle.bundle_p)
            ok_q, _, q = controller.validate_bundle(kp.public_bundle.bundle_q)
            assert ok_p, f"bundle_p did not resolve: {kp.public_bundle.bundle_p}"
            assert ok_q, f"bundle_q did not resolve: {kp.public_bundle.bundle_q}"
            assert p.name == kp.pokemon_p.name
            assert q.name == kp.pokemon_q.name

    def test_auto_bundle_fields_are_valid(self, controller):
        valid_fields = {
            "id", "form", "type_primary", "type_secondary",
            "height", "weight", "base_stat_total", "generation", "color"
        }
        kp = controller.generate_keypair()
        assert set(kp.public_bundle.bundle_p.keys()).issubset(valid_fields)
        assert set(kp.public_bundle.bundle_q.keys()).issubset(valid_fields)


# ---------------------------------------------------------------------------
# count_candidates
# ---------------------------------------------------------------------------

class TestCountCandidates:

    def test_no_bundle_returns_total_count(self, controller):
        assert controller.count_candidates() == len(TEST_RECORDS)

    def test_empty_bundle_returns_total_count(self, controller):
        assert controller.count_candidates({}) == len(TEST_RECORDS)

    def test_exact_bundle_returns_one(self, controller):
        assert controller.count_candidates(BUNDLE_BULBASAUR) == 1

    def test_partial_bundle_returns_correct_count(self, controller):
        # fire: charmander, cyndaquil, typhlosion, typhlosion-hisui = 4
        assert controller.count_candidates({"type_primary": "fire"}) == 4

    def test_no_match_returns_zero(self, controller):
        assert controller.count_candidates(BUNDLE_NO_MATCH) == 0

    def test_water_type_count(self, controller):
        # squirtle, mudkip = 2
        assert controller.count_candidates({"type_primary": "water"}) == 2

    def test_empty_database_returns_zero(self, empty_controller):
        assert empty_controller.count_candidates() == 0


# ---------------------------------------------------------------------------
# random_pokemon
# ---------------------------------------------------------------------------

class TestRandomPokemon:

    def test_returns_a_pokemon(self, controller):
        from pokedex_rsa.models.pokemon import Pokemon
        p = controller.random_pokemon()
        assert isinstance(p, Pokemon)

    def test_with_partial_bundle_returns_matching_pokemon(self, controller):
        p = controller.random_pokemon({"type_primary": "water"})
        assert p.type_primary == "water"

    def test_no_match_raises(self, controller):
        with pytest.raises(ResolutionError):
            controller.random_pokemon(BUNDLE_NO_MATCH)

    def test_empty_db_raises(self, empty_controller):
        with pytest.raises(EmptyDatabaseError):
            empty_controller.random_pokemon()

    def test_is_nondeterministic(self, controller):
        names = {controller.random_pokemon().name for _ in range(30)}
        assert len(names) > 1


# ---------------------------------------------------------------------------
# encrypt
# ---------------------------------------------------------------------------

class TestEncrypt:

    def test_returns_encrypted_message(self, controller):
        kp = controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_CHARMANDER)
        em = controller.encrypt("hello", kp.public_bundle)
        assert isinstance(em, EncryptedMessage)

    def test_ciphertext_is_list_of_ints(self, controller):
        kp = controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_CHARMANDER)
        em = controller.encrypt("hello", kp.public_bundle)
        assert isinstance(em.ciphertext, list)
        assert all(isinstance(c, int) for c in em.ciphertext)

    def test_public_bundle_preserved_in_message(self, controller):
        kp = controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_CHARMANDER)
        em = controller.encrypt("hello", kp.public_bundle)
        assert em.public_bundle == kp.public_bundle

    def test_ciphertext_differs_from_plaintext(self, controller):
        kp = controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_CHARMANDER)
        msg = "secret"
        em = controller.encrypt(msg, kp.public_bundle)
        plaintext_int = int.from_bytes(msg.encode(), "big")
        assert all(c != plaintext_int for c in em.ciphertext)

    def test_raises_on_empty_message(self, controller):
        kp = controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_CHARMANDER)
        with pytest.raises(ValueError):
            controller.encrypt("", kp.public_bundle)

    def test_raises_resolution_error_on_bad_bundle(self, controller):
        bad_bundle = PokedexPublicBundle(
            bundle_p=copy.deepcopy(BUNDLE_NO_MATCH),
            bundle_q=copy.deepcopy(BUNDLE_CHARMANDER),
        )
        with pytest.raises(ResolutionError):
            controller.encrypt("hello", bad_bundle)


# ---------------------------------------------------------------------------
# decrypt
# ---------------------------------------------------------------------------

class TestDecrypt:

    def test_decrypts_correctly(self, controller):
        kp = controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_CHARMANDER)
        msg = "Hello, Pokémon world!"
        em = controller.encrypt(msg, kp.public_bundle)
        assert controller.decrypt(em, kp.private_key) == msg

    def test_wrong_private_key_fails(self, controller):
        kp1 = controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_CHARMANDER)
        kp2 = controller.generate_keypair(BUNDLE_SQUIRTLE, BUNDLE_MUDKIP)
        em = controller.encrypt("secret", kp1.public_bundle)
        try:
            result = controller.decrypt(em, kp2.private_key)
            assert result != "secret"
        except (ValueError, OverflowError):
            pass

    def test_raises_resolution_error_if_bundle_unresolvable(self, controller):
        kp = controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_CHARMANDER)
        em = controller.encrypt("hello", kp.public_bundle)
        bad_bundle = PokedexPublicBundle(
            bundle_p=copy.deepcopy(BUNDLE_NO_MATCH),
            bundle_q=copy.deepcopy(BUNDLE_CHARMANDER),
        )
        bad_em = EncryptedMessage(
            ciphertext=em.ciphertext, public_bundle=bad_bundle)
        with pytest.raises(ResolutionError):
            controller.decrypt(bad_em, kp.private_key)


# ---------------------------------------------------------------------------
# Full pipeline round-trips
# ---------------------------------------------------------------------------

class TestPipelineRoundtrips:

    def _roundtrip(self, controller, message, bundle_p=None, bundle_q=None):
        kp = controller.generate_keypair(bundle_p, bundle_q)
        em = controller.encrypt(message, kp.public_bundle)
        return controller.decrypt(em, kp.private_key)

    def test_exact_bundles(self, controller):
        msg = "Exact bundle round-trip."
        assert self._roundtrip(
            controller, msg, BUNDLE_BULBASAUR, BUNDLE_CHARMANDER) == msg

    def test_partial_bundles(self, controller):
        msg = "Partial bundle round-trip."
        assert self._roundtrip(
            controller, msg, BUNDLE_PARTIAL_FIRE, BUNDLE_SQUIRTLE) == msg

    def test_fully_random(self, controller):
        msg = "Fully random round-trip."
        assert self._roundtrip(controller, msg) == msg

    def test_long_message(self, controller):
        msg = "Gotta catch em all! " * 50
        assert self._roundtrip(
            controller, msg, BUNDLE_BULBASAUR, BUNDLE_CHARMANDER) == msg

    def test_unicode_message(self, controller):
        msg = "Pokémon: 炎タイプ 🔥"
        assert self._roundtrip(
            controller, msg, BUNDLE_BULBASAUR, BUNDLE_CHARMANDER) == msg

    def test_regional_variant_keypair(self, controller):
        msg = "Hisuian forms are cool."
        assert self._roundtrip(
            controller, msg, BUNDLE_TYPHLOSION, BUNDLE_HISUI) == msg


# ---------------------------------------------------------------------------
# JSON serialization
# ---------------------------------------------------------------------------

class TestSerialization:

    def test_public_bundle_roundtrip_json(self, controller):
        kp = controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_CHARMANDER)
        raw = kp.public_bundle.to_json()
        restored = PokedexPublicBundle.from_json(raw)
        assert restored.bundle_p == kp.public_bundle.bundle_p
        assert restored.bundle_q == kp.public_bundle.bundle_q
        assert restored.e == kp.public_bundle.e

    def test_encrypted_message_roundtrip_json(self, controller):
        kp = controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_CHARMANDER)
        em = controller.encrypt("test message", kp.public_bundle)
        raw = em.to_json()
        restored = EncryptedMessage.from_json(raw)
        assert restored.ciphertext == em.ciphertext
        assert restored.public_bundle.bundle_p == em.public_bundle.bundle_p
        assert restored.public_bundle.bundle_q == em.public_bundle.bundle_q

    def test_decryption_after_json_roundtrip(self, controller):
        msg = "Serialized and back again."
        kp = controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_CHARMANDER)
        em = controller.encrypt(msg, kp.public_bundle)
        em_restored = EncryptedMessage.from_json(em.to_json())
        assert controller.decrypt(em_restored, kp.private_key) == msg


# ---------------------------------------------------------------------------
# validate_bundle
# ---------------------------------------------------------------------------

class TestValidateBundle:

    def test_valid_unique_bundle(self, controller):
        ok, err, pokemon = controller.validate_bundle(BUNDLE_BULBASAUR)
        assert ok is True
        assert err is None
        assert pokemon.name == "bulbasaur"

    def test_ambiguous_bundle_returns_false(self, controller):
        ok, err, pokemon = controller.validate_bundle(BUNDLE_PARTIAL_FIRE)
        assert ok is False
        assert err is not None
        assert pokemon is None

    def test_no_match_bundle_returns_false(self, controller):
        ok, err, pokemon = controller.validate_bundle(BUNDLE_NO_MATCH)
        assert ok is False
        assert err is not None
        assert pokemon is None
