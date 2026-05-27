"""
tests/test_cli.py

CLI input validation and error path tests.

Uses Click's CliRunner to invoke commands in-process without spawning a
subprocess. Each test class maps to one command. Tests focus on:

  - Missing required flags
  - Malformed / invalid JSON input
  - Conflicting flags (--verbose + --fileless)
  - Missing files in file mode
  - Ambiguous and no-match bundles
  - Empty or whitespace-only messages
  - Wrong / mismatched keys
  - Happy-path smoke tests for each output mode

The underlying crypto math and resolution logic are already covered by the
unit and integration test suites. These tests treat the CLI as a black box
and validate only what a user can observe: exit codes and output messages.
"""

from pokedex_rsa.views.cli import cli
import json
import os
import sys
import sqlite3
import pytest
from click.testing import CliRunner

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Shared test database + fixtures
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

# Unique bundles in the test DB
BP_BULBASAUR = '{"type_primary":"grass","type_secondary":"poison"}'
BP_SQUIRTLE = '{"type_primary":"water","generation":1}'
BP_CYNDAQUIL = '{"type_primary":"fire","weight":7.9}'
BP_TYPHLOSION = '{"type_primary":"fire","base_stat_total":534,"form":"default"}'
BP_HISUI = '{"type_primary":"fire","type_secondary":"ghost"}'
BP_MUDKIP = '{"type_primary":"water","generation":3}'

# Ambiguous and no-match bundles
BP_AMBIGUOUS = '{"type_primary":"fire"}'   # matches 4 records
BP_NO_MATCH = '{"type_primary":"dragon"}'  # matches 0 records


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def db_path(tmp_path):
    """Temporary SQLite DB pre-loaded with TEST_RECORDS."""
    db_file = tmp_path / "pokemon.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute(SCHEMA)
    conn.executemany(
        "INSERT INTO pokemon VALUES (?,?,?,?,?,?,?,?,?,?)", TEST_RECORDS)
    conn.commit()
    conn.close()
    return str(db_file)


@pytest.fixture
def patched_controller(db_path, monkeypatch):
    """
    Patch _controller() in cli.py to use the test DB instead of the
    default data/pokemon.db path.
    """
    from pokedex_rsa.controllers.encryption_controller import EncryptionController
    monkeypatch.setattr(
        "pokedex_rsa.views.cli._controller",
        lambda: EncryptionController(db_path=db_path)
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def invoke(runner, args, **kwargs):
    """Invoke the CLI and return the result."""
    return runner.invoke(cli, args, catch_exceptions=False, **kwargs)


def assert_error(result, fragment: str):
    """Assert the command exited with a non-zero code and output contains fragment."""
    assert result.exit_code != 0, (
        f"Expected non-zero exit code.\nOutput:\n{result.output}"
    )
    combined = (result.output or "") + \
        (result.stderr if hasattr(result, "stderr") else "")
    assert fragment.lower() in combined.lower(), (
        f"Expected '{fragment}' in output.\nOutput:\n{combined}"
    )


def assert_success(result, fragment: str = None):
    """Assert the command exited cleanly."""
    assert result.exit_code == 0, (
        f"Expected exit code 0, got {result.exit_code}.\nOutput:\n{result.output}"
    )
    if fragment:
        assert fragment.lower() in result.output.lower(), (
            f"Expected '{fragment}' in output.\nOutput:\n{result.output}"
        )


# ---------------------------------------------------------------------------
# validate command
# ---------------------------------------------------------------------------

class TestValidateCommand:

    def test_unique_bundle_succeeds(self, runner, patched_controller):
        result = invoke(runner, ["validate", "--bundle", BP_BULBASAUR])
        assert_success(result, "bulbasaur")

    def test_ambiguous_bundle_fails(self, runner, patched_controller):
        result = invoke(runner, ["validate", "--bundle", BP_AMBIGUOUS])
        assert_error(result, "matched")

    def test_no_match_bundle_fails(self, runner, patched_controller):
        result = invoke(runner, ["validate", "--bundle", BP_NO_MATCH])
        assert_error(result, "did not match")

    def test_malformed_json_fails(self, runner, patched_controller):
        result = invoke(runner, ["validate", "--bundle", "not-json"])
        assert_error(result, "could not parse")

    def test_json_array_instead_of_object_fails(self, runner, patched_controller):
        result = invoke(runner, ["validate", "--bundle", '["fire", "water"]'])
        assert_error(result, "must be a JSON object")

    def test_empty_object_fails(self, runner, patched_controller):
        # An empty bundle {} matches everything — ambiguous
        result = invoke(runner, ["validate", "--bundle", "{}"])
        assert_error(result, "matched")

    def test_missing_bundle_flag_fails(self, runner, patched_controller):
        result = runner.invoke(cli, ["validate"])
        assert result.exit_code != 0

    def test_invalid_field_name_fails(self, runner, patched_controller):
        result = invoke(
            runner, ["validate", "--bundle", '{"not_a_field":"value"}'])
        assert_error(result, "invalid")


# ---------------------------------------------------------------------------
# keygen command
# ---------------------------------------------------------------------------

class TestKeygenCommand:

    def test_fileless_success(self, runner, patched_controller):
        result = invoke(runner, [
            "keygen", "--fileless",
            "--bundle-p", BP_BULBASAUR,
            "--bundle-q", BP_SQUIRTLE,
        ])
        assert_success(result, "Private Key")
        assert_success(result, "Public Key")

    def test_fileless_shows_both_pokemon(self, runner, patched_controller):
        result = invoke(runner, [
            "keygen", "--fileless",
            "--bundle-p", BP_BULBASAUR,
            "--bundle-q", BP_SQUIRTLE,
        ])
        assert_success(result, "bulbasaur")
        assert_success(result, "squirtle")

    def test_file_mode_writes_files(self, runner, patched_controller, tmp_path):
        priv = str(tmp_path / "test.key")
        pub = str(tmp_path / "test.json")
        result = invoke(runner, [
            "keygen",
            "--bundle-p", BP_BULBASAUR,
            "--bundle-q", BP_SQUIRTLE,
            "--private-key-out", priv,
            "--public-key-out", pub,
        ])
        assert_success(result)
        assert os.path.exists(priv)
        assert os.path.exists(pub)

    def test_verbose_writes_files_and_prints(self, runner, patched_controller, tmp_path):
        priv = str(tmp_path / "test.key")
        pub = str(tmp_path / "test.json")
        result = invoke(runner, [
            "keygen", "--verbose",
            "--bundle-p", BP_BULBASAUR,
            "--bundle-q", BP_SQUIRTLE,
            "--private-key-out", priv,
            "--public-key-out", pub,
        ])
        assert_success(result, "Private Key")
        assert os.path.exists(priv)
        assert os.path.exists(pub)

    def test_verbose_and_fileless_are_mutually_exclusive(self, runner, patched_controller):
        result = invoke(runner, [
            "keygen", "--verbose", "--fileless",
            "--bundle-p", BP_BULBASAUR,
            "--bundle-q", BP_SQUIRTLE,
        ])
        assert_error(result, "mutually exclusive")

    def test_missing_bundle_p_uses_random(self, runner, patched_controller):
        # Omitting --bundle-p should succeed with random selection
        result = invoke(
            runner, ["keygen", "--fileless", "--bundle-q", BP_SQUIRTLE])
        assert_success(result, "Selected")

    def test_missing_bundle_q_uses_random(self, runner, patched_controller):
        # Omitting --bundle-q should succeed with random selection
        result = invoke(
            runner, ["keygen", "--fileless", "--bundle-p", BP_BULBASAUR])
        assert_success(result, "Selected")

    def test_no_bundles_succeeds(self, runner, patched_controller):
        result = invoke(runner, ["keygen", "--fileless"])
        assert_success(result, "Selected")

    def test_malformed_bundle_p_fails(self, runner, patched_controller):
        result = invoke(runner, [
            "keygen", "--fileless",
            "--bundle-p", "not-json",
            "--bundle-q", BP_SQUIRTLE,
        ])
        assert_error(result, "could not parse")

    def test_malformed_bundle_q_fails(self, runner, patched_controller):
        result = invoke(runner, [
            "keygen", "--fileless",
            "--bundle-p", BP_BULBASAUR,
            "--bundle-q", "{bad json",
        ])
        assert_error(result, "could not parse")

    def test_ambiguous_bundle_p_uses_restricted_random(self, runner, patched_controller):
        # Ambiguous bundle should succeed — picks randomly from matching pool
        result = invoke(runner, [
            "keygen", "--fileless",
            "--bundle-p", BP_AMBIGUOUS,
            "--bundle-q", BP_SQUIRTLE,
        ])
        assert_success(result, "Selected")

    def test_ambiguous_bundle_q_uses_restricted_random(self, runner, patched_controller):
        # Ambiguous bundle should succeed — picks randomly from matching pool
        result = invoke(runner, [
            "keygen", "--fileless",
            "--bundle-p", BP_BULBASAUR,
            "--bundle-q", BP_AMBIGUOUS,
        ])
        assert_success(result, "Selected")

    def test_no_match_bundle_p_fails(self, runner, patched_controller):
        result = invoke(runner, [
            "keygen", "--fileless",
            "--bundle-p", BP_NO_MATCH,
            "--bundle-q", BP_SQUIRTLE,
        ])
        assert_error(result, "did not match")

    def test_same_pokemon_both_bundles_fails(self, runner, patched_controller):
        result = invoke(runner, [
            "keygen", "--fileless",
            "--bundle-p", BP_BULBASAUR,
            "--bundle-q", BP_BULBASAUR,
        ])
        assert_error(result, "same pokemon")

    def test_output_public_key_is_valid_json(self, runner, patched_controller):
        result = invoke(runner, [
            "keygen", "--fileless",
            "--bundle-p", BP_BULBASAUR,
            "--bundle-q", BP_SQUIRTLE,
        ])
        assert_success(result)
        # Extract the public key line and verify it parses as JSON
        for line in result.output.splitlines():
            line = line.strip()
            if line.startswith('{"bundle_p"'):
                parsed = json.loads(line)
                assert "bundle_p" in parsed
                assert "bundle_q" in parsed
                assert "e" in parsed
                break
        else:
            pytest.fail("Could not find public key JSON in output.")


# ---------------------------------------------------------------------------
# encrypt command
# ---------------------------------------------------------------------------

class TestEncryptCommand:

    @pytest.fixture
    def public_key_json(self, runner, patched_controller):
        """Generate a valid public key JSON string for use in encrypt tests."""
        result = invoke(runner, [
            "keygen", "--fileless",
            "--bundle-p", BP_BULBASAUR,
            "--bundle-q", BP_SQUIRTLE,
        ])
        for line in result.output.splitlines():
            line = line.strip()
            if line.startswith('{"bundle_p"'):
                return line
        pytest.fail("Could not extract public key from keygen output.")

    def test_fileless_success(self, runner, patched_controller, public_key_json):
        result = invoke(runner, [
            "encrypt", "--fileless",
            "--message", "Hello, Trainer!",
            "--public-key", public_key_json,
        ])
        assert_success(result, "ciphertext")

    def test_fileless_output_is_valid_json(self, runner, patched_controller, public_key_json):
        result = invoke(runner, [
            "encrypt", "--fileless",
            "--message", "Hello!",
            "--public-key", public_key_json,
        ])
        assert_success(result)
        for line in result.output.splitlines():
            line = line.strip()
            if line.startswith('{"ciphertext"'):
                parsed = json.loads(line)
                assert "ciphertext" in parsed
                assert "public_bundle" in parsed
                break
        else:
            pytest.fail("Could not find encrypted JSON in output.")

    def test_file_mode_writes_encrypted_file(self, runner, patched_controller, public_key_json, tmp_path):
        pub_file = tmp_path / "public.json"
        enc_file = tmp_path / "encrypted.json"
        pub_file.write_text(
            json.dumps({"bundle_p": json.loads(BP_BULBASAUR),
                        "bundle_q": json.loads(BP_SQUIRTLE), "e": 65537})
        )
        result = invoke(runner, [
            "encrypt",
            "--message", "Hello!",
            "--public-key-file", str(pub_file),
            "--out", str(enc_file),
        ])
        assert_success(result)
        assert enc_file.exists()

    def test_empty_message_fails(self, runner, patched_controller, public_key_json):
        result = invoke(runner, [
            "encrypt", "--fileless",
            "--message", "   ",
            "--public-key", public_key_json,
        ])
        assert_error(result, "empty")

    def test_fileless_missing_public_key_fails(self, runner, patched_controller):
        result = invoke(runner, [
            "encrypt", "--fileless",
            "--message", "Hello!",
        ])
        assert_error(result, "requires --public-key")

    def test_malformed_public_key_json_fails(self, runner, patched_controller):
        result = invoke(runner, [
            "encrypt", "--fileless",
            "--message", "Hello!",
            "--public-key", "not-json",
        ])
        assert_error(result, "could not parse")

    def test_public_key_missing_fields_fails(self, runner, patched_controller):
        result = invoke(runner, [
            "encrypt", "--fileless",
            "--message", "Hello!",
            "--public-key", '{"bundle_p": {}}',  # missing bundle_q
        ])
        assert_error(result, "could not parse")

    def test_verbose_and_fileless_mutually_exclusive(self, runner, patched_controller, public_key_json):
        result = invoke(runner, [
            "encrypt", "--verbose", "--fileless",
            "--message", "Hello!",
            "--public-key", public_key_json,
        ])
        assert_error(result, "mutually exclusive")

    def test_missing_public_key_file_fails(self, runner, patched_controller, tmp_path):
        result = invoke(runner, [
            "encrypt",
            "--message", "Hello!",
            "--public-key-file", str(tmp_path / "nonexistent.json"),
        ])
        assert_error(result, "not found")

    def test_unresolvable_bundle_in_public_key_fails(self, runner, patched_controller):
        bad_key = json.dumps({
            "bundle_p": {"type_primary": "dragon"},
            "bundle_q": json.loads(BP_SQUIRTLE),
            "e": 65537,
        })
        result = invoke(runner, [
            "encrypt", "--fileless",
            "--message", "Hello!",
            "--public-key", bad_key,
        ])
        assert_error(result, "did not match")


# ---------------------------------------------------------------------------
# decrypt command
# ---------------------------------------------------------------------------

class TestDecryptCommand:

    @pytest.fixture
    def keypair_and_message(self, runner, patched_controller):
        """
        Returns (private_key_json, encrypted_json) for a valid fileless
        keygen + encrypt pipeline so decrypt tests have real inputs.
        """
        # keygen
        kg = invoke(runner, [
            "keygen", "--fileless",
            "--bundle-p", BP_BULBASAUR,
            "--bundle-q", BP_SQUIRTLE,
        ])
        private_key = None
        public_key = None
        for line in kg.output.splitlines():
            line = line.strip()
            if line.startswith('{"n"'):
                private_key = line
            if line.startswith('{"bundle_p"'):
                public_key = line

        assert private_key and public_key, "keygen fixture failed"

        # encrypt
        enc = invoke(runner, [
            "encrypt", "--fileless",
            "--message", "Test message for decrypt.",
            "--public-key", public_key,
        ])
        encrypted = None
        for line in enc.output.splitlines():
            line = line.strip()
            if line.startswith('{"ciphertext"'):
                encrypted = line

        assert encrypted, "encrypt fixture failed"
        return private_key, encrypted

    def test_fileless_success(self, runner, patched_controller, keypair_and_message):
        private_key, encrypted = keypair_and_message
        result = invoke(runner, [
            "decrypt", "--fileless",
            "--private-key", private_key,
            "--encrypted", encrypted,
        ])
        assert_success(result, "Test message for decrypt.")

    def test_file_mode_writes_plaintext_file(self, runner, patched_controller,
                                             keypair_and_message, tmp_path):
        private_key, encrypted = keypair_and_message
        priv_file = tmp_path / "private.key"
        enc_file = tmp_path / "encrypted.json"
        plain_file = tmp_path / "plaintext.txt"

        priv_file.write_text(private_key)
        enc_file.write_text(encrypted)

        result = invoke(runner, [
            "decrypt",
            "--private-key-file", str(priv_file),
            "--encrypted-file",   str(enc_file),
            "--out",              str(plain_file),
        ])
        assert_success(result)
        assert plain_file.exists()
        assert plain_file.read_text() == "Test message for decrypt."

    def test_verbose_prints_plaintext(self, runner, patched_controller,
                                      keypair_and_message, tmp_path):
        private_key, encrypted = keypair_and_message
        priv_file = tmp_path / "private.key"
        enc_file = tmp_path / "encrypted.json"
        priv_file.write_text(private_key)
        enc_file.write_text(encrypted)

        result = invoke(runner, [
            "decrypt", "--verbose",
            "--private-key-file", str(priv_file),
            "--encrypted-file",   str(enc_file),
            "--out", str(tmp_path / "plaintext.txt"),
        ])
        assert_success(result, "Test message for decrypt.")

    def test_fileless_missing_private_key_fails(self, runner, patched_controller,
                                                keypair_and_message):
        _, encrypted = keypair_and_message
        result = invoke(runner, [
            "decrypt", "--fileless",
            "--encrypted", encrypted,
        ])
        assert_error(result, "requires --private-key")

    def test_fileless_missing_encrypted_fails(self, runner, patched_controller,
                                              keypair_and_message):
        private_key, _ = keypair_and_message
        result = invoke(runner, [
            "decrypt", "--fileless",
            "--private-key", private_key,
        ])
        assert_error(result, "requires --encrypted")

    def test_malformed_private_key_fails(self, runner, patched_controller,
                                         keypair_and_message):
        _, encrypted = keypair_and_message
        result = invoke(runner, [
            "decrypt", "--fileless",
            "--private-key", "not-json",
            "--encrypted", encrypted,
        ])
        assert_error(result, "could not parse private key")

    def test_private_key_missing_n_field_fails(self, runner, patched_controller,
                                               keypair_and_message):
        _, encrypted = keypair_and_message
        result = invoke(runner, [
            "decrypt", "--fileless",
            "--private-key", '{"d": 12345}',
            "--encrypted", encrypted,
        ])
        assert_error(result, "could not parse private key")

    def test_private_key_missing_d_field_fails(self, runner, patched_controller,
                                               keypair_and_message):
        _, encrypted = keypair_and_message
        result = invoke(runner, [
            "decrypt", "--fileless",
            "--private-key", '{"n": 12345}',
            "--encrypted", encrypted,
        ])
        assert_error(result, "could not parse private key")

    def test_malformed_encrypted_message_fails(self, runner, patched_controller,
                                               keypair_and_message):
        private_key, _ = keypair_and_message
        result = invoke(runner, [
            "decrypt", "--fileless",
            "--private-key", private_key,
            "--encrypted", "not-json",
        ])
        assert_error(result, "could not parse encrypted message")

    def test_missing_private_key_file_fails(self, runner, patched_controller, tmp_path):
        result = invoke(runner, [
            "decrypt",
            "--private-key-file", str(tmp_path / "nonexistent.key"),
            "--encrypted-file",   str(tmp_path / "nonexistent.json"),
        ])
        assert_error(result, "not found")

    def test_missing_encrypted_file_fails(self, runner, patched_controller,
                                          keypair_and_message, tmp_path):
        private_key, _ = keypair_and_message
        priv_file = tmp_path / "private.key"
        priv_file.write_text(private_key)
        result = invoke(runner, [
            "decrypt",
            "--private-key-file", str(priv_file),
            "--encrypted-file",   str(tmp_path / "nonexistent.json"),
        ])
        assert_error(result, "not found")

    def test_verbose_and_fileless_mutually_exclusive(self, runner, patched_controller,
                                                     keypair_and_message):
        private_key, encrypted = keypair_and_message
        result = invoke(runner, [
            "decrypt", "--verbose", "--fileless",
            "--private-key", private_key,
            "--encrypted", encrypted,
        ])
        assert_error(result, "mutually exclusive")

    def test_wrong_private_key_fails_or_garbles(self, runner, patched_controller):
        """
        Encrypting with one keypair and decrypting with a different private
        key should either error or produce output that is not the original message.
        """
        # Generate two separate keypairs
        kg1 = invoke(runner, ["keygen", "--fileless",
                              "--bundle-p", BP_BULBASAUR, "--bundle-q", BP_SQUIRTLE])
        kg2 = invoke(runner, ["keygen", "--fileless",
                              "--bundle-p", BP_CYNDAQUIL, "--bundle-q", BP_MUDKIP])

        priv1 = next(l.strip() for l in kg1.output.splitlines()
                     if l.strip().startswith('{"n"'))
        priv2 = next(l.strip() for l in kg2.output.splitlines()
                     if l.strip().startswith('{"n"'))
        pub1 = next(l.strip() for l in kg1.output.splitlines()
                    if l.strip().startswith('{"bundle_p"'))

        enc = invoke(runner, ["encrypt", "--fileless",
                              "--message", "secret",
                              "--public-key", pub1])
        encrypted = next(l.strip() for l in enc.output.splitlines()
                         if l.strip().startswith('{"ciphertext"'))

        result = invoke(runner, ["decrypt", "--fileless",
                                 "--private-key", priv2,
                                 "--encrypted", encrypted])

        # Either it errors, or the output does not contain the original message
        if result.exit_code == 0:
            assert "secret" not in result.output
        else:
            assert result.exit_code != 0
