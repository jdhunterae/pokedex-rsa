"""
tests/test_encryption_controller.py

End-to-end tests for EncryptionController.

Tests cover:
  - Keypair generation (success, resolution errors, same-pokemon error)
  - Encrypt (success, resolution errors, empty message)
  - Decrypt (success, wrong key, corrupted ciphertext)
  - Full pipeline round-trips (short, long, unicode messages)
  - PokedexPublicBundle and EncryptedMessage JSON serialization
  - validate_bundle helper

Uses the same in-memory SQLite fixture pattern as the other test modules.
"""

from pokedex_rsa.models.crypto import derive_prime, generate_keypair
from pokedex_rsa.controllers.encryption_controller import (
    EncryptionController,
    PokedexPublicBundle,
    PokedexKeypair,
    EncryptedMessage,
    ResolutionError,
    SamePokemonError,
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

# Bundles that uniquely resolve in the test DB
# only grass type
BUNDLE_BULBASAUR = {"type_primary": "grass"}
BUNDLE_CHARMANDER = {"type_primary": "fire",
                     "generation": 1}        # only fire gen1
BUNDLE_SQUIRTLE = {"type_primary": "water",
                   "generation": 1}       # only water gen1
BUNDLE_CYNDAQUIL = {"type_primary": "fire",
                    "weight": 7.9}          # unique weight
BUNDLE_TYPHLOSION = {"type_primary": "fire",
                     "base_stat_total": 534, "form": "default"}
BUNDLE_HISUI = {"type_primary": "fire", "type_secondary": "ghost"}
BUNDLE_MUDKIP = {"type_primary": "water",
                 "generation": 3}       # only water gen3

# Ambiguous bundle (matches charmander, cyndaquil, typhlosion, typhlosion-hisui)
BUNDLE_AMBIGUOUS = {"type_primary": "fire"}

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


# ---------------------------------------------------------------------------
# generate_keypair
# ---------------------------------------------------------------------------

class TestGenerateKeypair:

    def test_returns_pokedex_keypair(self, controller):
        kp = controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_CHARMANDER)
        assert isinstance(kp, PokedexKeypair)

    def test_pokemon_names_are_correct(self, controller):
        kp = controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_CHARMANDER)
        assert kp.pokemon_p.name == "bulbasaur"
        assert kp.pokemon_q.name == "charmander"

    def test_public_bundle_carries_input_bundles(self, controller):
        kp = controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_CHARMANDER)
        assert kp.public_bundle.bundle_p == BUNDLE_BULBASAUR
        assert kp.public_bundle.bundle_q == BUNDLE_CHARMANDER

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

    def test_raises_resolution_error_on_no_match(self, controller):
        with pytest.raises(ResolutionError):
            controller.generate_keypair(BUNDLE_NO_MATCH, BUNDLE_CHARMANDER)

    def test_raises_resolution_error_on_ambiguous(self, controller):
        with pytest.raises(ResolutionError):
            controller.generate_keypair(BUNDLE_AMBIGUOUS, BUNDLE_CHARMANDER)

    def test_raises_same_pokemon_error(self, controller):
        with pytest.raises(SamePokemonError):
            controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_BULBASAUR)

    def test_same_pokemon_error_carries_pokemon(self, controller):
        with pytest.raises(SamePokemonError) as exc_info:
            controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_BULBASAUR)
        assert exc_info.value.pokemon.name == "bulbasaur"

    def test_works_with_regional_variant(self, controller):
        kp = controller.generate_keypair(BUNDLE_TYPHLOSION, BUNDLE_HISUI)
        assert kp.pokemon_p.name == "typhlosion"
        assert kp.pokemon_q.name == "typhlosion-hisui"

    def test_resolution_error_suggests_fields_on_ambiguous(self, controller):
        with pytest.raises(ResolutionError) as exc_info:
            controller.generate_keypair(BUNDLE_AMBIGUOUS, BUNDLE_CHARMANDER)
        # Error message should mention fields to try
        assert "bundle_p" in str(exc_info.value).lower(
        ) or "add" in str(exc_info.value).lower()


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
            bundle_p=BUNDLE_NO_MATCH,
            bundle_q=BUNDLE_CHARMANDER,
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
            pass  # raising is also acceptable

    def test_raises_resolution_error_if_bundle_unresolvable(self, controller):
        kp = controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_CHARMANDER)
        em = controller.encrypt("hello", kp.public_bundle)
        # Build a fresh EncryptedMessage with a bad bundle rather than mutating the original
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

    def _roundtrip(self, controller, message, bundle_p, bundle_q):
        kp = controller.generate_keypair(bundle_p, bundle_q)
        em = controller.encrypt(message, kp.public_bundle)
        return controller.decrypt(em, kp.private_key)

    def test_short_message(self, controller):
        assert self._roundtrip(
            controller, "Hi!", BUNDLE_BULBASAUR, BUNDLE_CHARMANDER) == "Hi!"

    def test_sentence_message(self, controller):
        msg = "The quick brown Arcanine jumps over the lazy Snorlax."
        assert self._roundtrip(
            controller, msg, BUNDLE_BULBASAUR, BUNDLE_CHARMANDER) == msg

    def test_long_message(self, controller):
        msg = "Gotta catch em all! " * 50
        assert self._roundtrip(
            controller, msg, BUNDLE_SQUIRTLE, BUNDLE_MUDKIP) == msg

    def test_unicode_message(self, controller):
        msg = "Pokémon: 炎タイプ 🔥"
        assert self._roundtrip(
            controller, msg, BUNDLE_BULBASAUR, BUNDLE_CHARMANDER) == msg

    def test_regional_variant_keypair(self, controller):
        msg = "Hisuian forms are cool."
        assert self._roundtrip(
            controller, msg, BUNDLE_TYPHLOSION, BUNDLE_HISUI) == msg

    def test_different_pokemon_pairs_produce_different_ciphertext(self, controller):
        msg = "same message"
        kp1 = controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_CHARMANDER)
        kp2 = controller.generate_keypair(BUNDLE_SQUIRTLE,  BUNDLE_MUDKIP)
        em1 = controller.encrypt(msg, kp1.public_bundle)
        em2 = controller.encrypt(msg, kp2.public_bundle)
        assert em1.ciphertext != em2.ciphertext


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

    def test_public_bundle_json_is_valid_json(self, controller):
        kp = controller.generate_keypair(BUNDLE_BULBASAUR, BUNDLE_CHARMANDER)
        raw = kp.public_bundle.to_json()
        parsed = json.loads(raw)
        assert "bundle_p" in parsed
        assert "bundle_q" in parsed
        assert "e" in parsed

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

        # Simulate transmitting as JSON and restoring
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
        ok, err, pokemon = controller.validate_bundle(BUNDLE_AMBIGUOUS)
        assert ok is False
        assert err is not None
        assert pokemon is None

    def test_no_match_bundle_returns_false(self, controller):
        ok, err, pokemon = controller.validate_bundle(BUNDLE_NO_MATCH)
        assert ok is False
        assert err is not None
        assert pokemon is None

    def test_error_message_is_informative(self, controller):
        _, err, _ = controller.validate_bundle(BUNDLE_AMBIGUOUS)
        assert err is not None
        assert len(err) > 20  # not just an empty or trivial string
