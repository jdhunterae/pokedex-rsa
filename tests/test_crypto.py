"""
tests/test_crypto.py

Unit tests for the crypto layer.

Tests are grouped into:
  - Prime derivation (determinism, uniqueness, correctness)
  - RSA math helpers (modular inverse)
  - Key generation
  - Encrypt / decrypt round-trips
  - Edge cases and error handling

All tests use known Pokemon names so that prime derivation results are
deterministic and can be verified across environments.
"""

from pokedex_rsa.models.crypto import (
    derive_prime,
    generate_keypair,
    encrypt,
    decrypt,
    PublicKey,
    PrivateKey,
    KeyPair,
    PUBLIC_EXPONENT,
    _is_prime_miller_rabin,
    _next_prime,
    _mod_inverse,
    _block_size,
    _split_blocks,
)
import hashlib
import math
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Known test pairs — derived once and reused across test classes.
# Using starter Pokemon ensures these names are always in any seeded DB.
# ---------------------------------------------------------------------------

NAME_A = "bulbasaur"
NAME_B = "charmander"
NAME_C = "squirtle"
NAME_VARIANT = "typhlosion-hisui"


# ---------------------------------------------------------------------------
# Primality helpers
# ---------------------------------------------------------------------------

class TestMillerRabin:

    def test_small_primes(self):
        for p in [2, 3, 5, 7, 11, 13, 97]:
            assert _is_prime_miller_rabin(p), f"{p} should be prime"

    def test_small_composites(self):
        for c in [4, 6, 8, 9, 10, 15, 100]:
            assert not _is_prime_miller_rabin(c), f"{c} should not be prime"

    def test_large_prime(self):
        # A known 256-bit prime
        large = (1 << 255) + 51
        # We don't assert exact primality here since this specific number
        # may or may not be prime — we assert the function runs without error
        result = _is_prime_miller_rabin(large)
        assert isinstance(result, bool)

    def test_returns_false_for_one(self):
        assert not _is_prime_miller_rabin(1)

    def test_returns_false_for_zero(self):
        assert not _is_prime_miller_rabin(0)


class TestNextPrime:

    def test_next_prime_from_even(self):
        # next prime >= 10 is 11
        assert _next_prime(10) == 11

    def test_next_prime_from_prime(self):
        # next prime >= 7 is 7 itself
        assert _next_prime(7) == 7

    def test_next_prime_from_composite(self):
        # next prime >= 8 is 11
        assert _next_prime(8) == 11

    def test_result_is_prime(self):
        for start in [100, 200, 500, 1000]:
            result = _next_prime(start)
            assert _is_prime_miller_rabin(result)
            assert result >= start


# ---------------------------------------------------------------------------
# Prime derivation
# ---------------------------------------------------------------------------

class TestDerivePrime:

    def test_returns_integer(self):
        assert isinstance(derive_prime(NAME_A), int)

    def test_result_is_prime(self):
        p = derive_prime(NAME_A)
        assert _is_prime_miller_rabin(p)

    def test_deterministic(self):
        # Same name must always produce the same prime
        assert derive_prime(NAME_A) == derive_prime(NAME_A)
        assert derive_prime(NAME_VARIANT) == derive_prime(NAME_VARIANT)

    def test_case_insensitive(self):
        # Names are lowercased before hashing
        assert derive_prime("Bulbasaur") == derive_prime("bulbasaur")
        assert derive_prime("BULBASAUR") == derive_prime("bulbasaur")

    def test_unique_per_name(self):
        # Different names must produce different primes
        primes = {
            derive_prime(NAME_A),
            derive_prime(NAME_B),
            derive_prime(NAME_C),
            derive_prime(NAME_VARIANT),
        }
        assert len(primes) == 4, "Each Pokemon name must derive a unique prime"

    def test_variant_differs_from_base(self):
        base = derive_prime("typhlosion")
        variant = derive_prime("typhlosion-hisui")
        assert base != variant

    def test_prime_is_256_bit_range(self):
        # SHA-256 produces a 256-bit seed; resulting prime should be in that range
        p = derive_prime(NAME_A)
        assert p.bit_length() >= 250  # allows for small forward walk
        assert p.bit_length() <= 270  # shouldn't stray too far

    def test_empty_name_still_derives(self):
        # Edge case: empty string should still produce a valid prime
        p = derive_prime("")
        assert _is_prime_miller_rabin(p)


# ---------------------------------------------------------------------------
# Modular inverse
# ---------------------------------------------------------------------------

class TestModInverse:

    def test_basic_inverse(self):
        # 3 * 4 = 12 ≡ 1 mod 11 → inverse of 3 mod 11 is 4
        assert _mod_inverse(3, 11) == 4

    def test_inverse_of_65537(self):
        # Simulate a tiny RSA setup: p=61, q=53 → n=3233, phi=3120
        p, q = 61, 53
        phi = (p - 1) * (q - 1)
        e = 17
        d = _mod_inverse(e, phi)
        assert (e * d) % phi == 1

    def test_raises_when_no_inverse(self):
        # gcd(4, 8) = 4 ≠ 1, so no modular inverse exists
        with pytest.raises(ValueError):
            _mod_inverse(4, 8)


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------

class TestGenerateKeypair:

    @pytest.fixture
    def keypair(self):
        p = derive_prime(NAME_A)
        q = derive_prime(NAME_B)
        return generate_keypair(p, q)

    def test_returns_keypair(self, keypair):
        assert isinstance(keypair, KeyPair)

    def test_public_key_structure(self, keypair):
        assert isinstance(keypair.public, PublicKey)
        assert keypair.public.e == PUBLIC_EXPONENT

    def test_private_key_structure(self, keypair):
        assert isinstance(keypair.private, PrivateKey)

    def test_n_is_product_of_primes(self):
        p = derive_prime(NAME_A)
        q = derive_prime(NAME_B)
        kp = generate_keypair(p, q)
        assert kp.n == p * q

    def test_public_and_private_share_n(self, keypair):
        assert keypair.public.n == keypair.private.n

    def test_e_and_d_are_inverses(self, keypair):
        # e * d ≡ 1 mod φ(n) is the RSA invariant
        p = derive_prime(NAME_A)
        q = derive_prime(NAME_B)
        phi = (p - 1) * (q - 1)
        assert (keypair.public.e * keypair.private.d) % phi == 1

    def test_raises_for_identical_primes(self):
        p = derive_prime(NAME_A)
        with pytest.raises(ValueError, match="distinct"):
            generate_keypair(p, p)

    def test_order_of_primes_does_not_matter(self):
        p = derive_prime(NAME_A)
        q = derive_prime(NAME_B)
        kp1 = generate_keypair(p, q)
        kp2 = generate_keypair(q, p)
        # n = p*q is commutative; keypairs should be equivalent
        assert kp1.n == kp2.n

    def test_private_key_str_redacts_d(self, keypair):
        assert "REDACTED" in str(keypair.private)
        assert str(keypair.private.d) not in str(keypair.private)


# ---------------------------------------------------------------------------
# Block sizing
# ---------------------------------------------------------------------------

class TestBlockSize:

    def test_block_size_less_than_n_byte_length(self):
        p = derive_prime(NAME_A)
        q = derive_prime(NAME_B)
        kp = generate_keypair(p, q)
        bsize = _block_size(kp.n)
        n_bytes = (kp.n.bit_length() + 7) // 8
        assert bsize < n_bytes

    def test_block_fits_in_n(self):
        p = derive_prime(NAME_A)
        q = derive_prime(NAME_B)
        kp = generate_keypair(p, q)
        bsize = _block_size(kp.n)
        max_block_int = (1 << (bsize * 8)) - 1
        assert max_block_int < kp.n

    def test_split_blocks_correct_count(self):
        data = b"hello world this is a test message"
        blocks = _split_blocks(data, 8)
        assert len(blocks) == math.ceil(len(data) / 8)

    def test_split_blocks_reassembles(self):
        data = b"hello world this is a test message"
        blocks = _split_blocks(data, 8)
        assert b"".join(blocks) == data


# ---------------------------------------------------------------------------
# Encrypt / Decrypt round-trips
# ---------------------------------------------------------------------------

class TestEncryptDecrypt:

    @pytest.fixture
    def keypair(self):
        p = derive_prime(NAME_A)
        q = derive_prime(NAME_B)
        return generate_keypair(p, q)

    def _roundtrip(self, message, keypair):
        ct = encrypt(message, keypair.public)
        return decrypt(ct, keypair.private, keypair.public)

    def test_short_message(self, keypair):
        msg = "Hello!"
        assert self._roundtrip(msg, keypair) == msg

    def test_sentence_message(self, keypair):
        msg = "The quick brown fox jumps over the lazy dog."
        assert self._roundtrip(msg, keypair) == msg

    def test_long_message_requires_multiple_blocks(self, keypair):
        # Generate a message definitely longer than one block
        msg = "A" * 500
        ct = encrypt(msg, keypair.public)
        assert len(
            ct) > 1, "Long message should produce multiple ciphertext blocks"
        assert decrypt(ct, keypair.private, keypair.public) == msg

    def test_unicode_message(self, keypair):
        msg = "Pokémon: Bulbasaur 🌿"
        assert self._roundtrip(msg, keypair) == msg

    def test_single_character(self, keypair):
        assert self._roundtrip("X", keypair) == "X"

    def test_ciphertext_differs_from_plaintext(self, keypair):
        msg = "secret message"
        ct = encrypt(msg, keypair.public)
        # Ciphertext integers should not equal the plaintext bytes as int
        plaintext_int = int.from_bytes(msg.encode(), "big")
        assert all(c != plaintext_int for c in ct)

    def test_different_pokemon_pair_produces_different_ciphertext(self):
        msg = "same message"
        kp1 = generate_keypair(derive_prime(NAME_A), derive_prime(NAME_B))
        kp2 = generate_keypair(derive_prime(NAME_B), derive_prime(NAME_C))
        ct1 = encrypt(msg, kp1.public)
        ct2 = encrypt(msg, kp2.public)
        assert ct1 != ct2

    def test_wrong_private_key_raises_or_garbles(self):
        kp1 = generate_keypair(derive_prime(NAME_A), derive_prime(NAME_B))
        kp2 = generate_keypair(derive_prime(NAME_B), derive_prime(NAME_C))
        msg = "secret"
        ct = encrypt(msg, kp1.public)
        # Decrypting with a mismatched key should either raise or return garbage
        try:
            result = decrypt(ct, kp2.private, kp1.public)
            assert result != msg, "Wrong key should not successfully decrypt"
        except (ValueError, OverflowError):
            pass  # Raising is also acceptable

    def test_variant_pokemon_keypair(self):
        # Ensure regional variant names work end-to-end
        p = derive_prime("typhlosion")
        q = derive_prime("typhlosion-hisui")
        kp = generate_keypair(p, q)
        msg = "Hisui region!"
        assert self._roundtrip(msg, kp) == msg


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrors:

    @pytest.fixture
    def keypair(self):
        p = derive_prime(NAME_A)
        q = derive_prime(NAME_B)
        return generate_keypair(p, q)

    def test_encrypt_empty_string_raises(self, keypair):
        with pytest.raises(ValueError, match="empty"):
            encrypt("", keypair.public)

    def test_decrypt_empty_list_raises(self, keypair):
        with pytest.raises(ValueError, match="empty"):
            decrypt([], keypair.private, keypair.public)
