"""
models/crypto.py

Prime derivation and RSA encryption/decryption engine.

This module is the cryptographic heart of Pokedex RSA. It implements:

  1. Deterministic prime derivation from Pokemon names via SHA-256
  2. RSA keypair generation from two derived primes
  3. Block-based message encryption and decryption

Design notes
------------
Prime derivation
    A Pokemon's name (its PokeAPI slug, e.g. 'typhlosion-hisui') is hashed
    with SHA-256 to produce a 256-bit integer. That integer is used as the
    starting point for a prime search — we walk forward through odd numbers
    until we find a prime. Because SHA-256 is collision-resistant, two
    different names will always produce starting points far enough apart on
    the number line that they cannot converge on the same prime.

    This guarantees a unique prime per Pokemon name without requiring any
    lookup table or pre-computation.

Block encryption
    RSA natively encrypts integers smaller than n (the modulus). Since our
    primes are ~256 bits, n is ~512 bits (~154 decimal digits). Any message
    longer than ~19 characters could exceed n as a raw integer. To handle
    arbitrary-length messages, we split the plaintext into fixed-size byte
    blocks, encrypt each block independently, and reassemble on decryption.

    Block size is derived from n at encryption time so the system
    automatically scales as the prime space grows with future Pokedex
    expansions.

Key size note
    Our primes are ~256 bits, yielding a 512-bit modulus. 512-bit RSA is
    not considered secure by modern standards (it has been factored in
    practice since 1999). This is intentional — the prime space is bounded
    by the Pokedex, and this project is a demonstration of RSA principles
    rather than a production cryptosystem. The architecture is sound; only
    the key size is a known limitation.
"""

import hashlib
import math
import os
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PublicKey:
    """
    RSA public key.

    n : modulus  (p * q)
    e : public exponent (typically 65537)
    """
    n: int
    e: int

    def __str__(self) -> str:
        return f"PublicKey(n={self.n}, e={self.e})"


@dataclass(frozen=True)
class PrivateKey:
    """
    RSA private key.

    n : modulus  (p * q, same as public key)
    d : private exponent (modular inverse of e mod φ(n))
    """
    n: int
    d: int

    def __str__(self) -> str:
        # Never print d in full — truncate for safety even in demos
        return f"PrivateKey(n={self.n}, d=[REDACTED])"


@dataclass(frozen=True)
class KeyPair:
    """A matched RSA public/private key pair."""
    public:  PublicKey
    private: PrivateKey

    @property
    def n(self) -> int:
        return self.public.n


# ---------------------------------------------------------------------------
# Primality testing
# ---------------------------------------------------------------------------

def _is_prime_miller_rabin(n: int, rounds: int = 20) -> bool:
    """
    Miller-Rabin probabilistic primality test.

    For a 256-bit candidate the probability of a false positive after
    20 rounds is less than 4^-20 ≈ 10^-12, which is sufficient for our
    purposes.

    Parameters
    ----------
    n      : candidate integer (must be > 2)
    rounds : number of witness rounds (more = more certain, slower)
    """
    if n < 2:
        return False
    if n == 2 or n == 3:
        return True
    if n % 2 == 0:
        return False

    # Small prime fast path — eliminates most composites immediately
    SMALL_PRIMES = [
        3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41,
        43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97
    ]
    for sp in SMALL_PRIMES:
        if n == sp:
            return True
        if n % sp == 0:
            return False

    # Write n-1 as 2^r * d
    r, d = 0, n - 1
    while d % 2 == 0:
        r += 1
        d //= 2

    # Miller-Rabin witness loop
    import random
    rng = random.SystemRandom()
    for _ in range(rounds):
        a = rng.randrange(2, n - 1)
        x = pow(a, d, n)

        if x == 1 or x == n - 1:
            continue

        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False

    return True


def _next_prime(start: int) -> int:
    """
    Find the next prime >= start.

    Forces start to be odd (even numbers > 2 cannot be prime) then walks
    forward in steps of 2, testing each candidate with Miller-Rabin.
    """
    candidate = start | 1  # force odd
    while not _is_prime_miller_rabin(candidate):
        candidate += 2
    return candidate


# ---------------------------------------------------------------------------
# Prime derivation
# ---------------------------------------------------------------------------

def derive_prime(pokemon_name: str) -> int:
    """
    Deterministically derive a large prime from a Pokemon's name.

    Process:
      1. UTF-8 encode the PokeAPI slug (e.g. 'typhlosion-hisui')
      2. SHA-256 hash → 256-bit integer
      3. Walk forward from that integer until a prime is found

    The result is uniquely tied to the name: SHA-256 collision resistance
    guarantees that two different names produce starting points far enough
    apart on the number line that they cannot converge on the same prime.

    Parameters
    ----------
    pokemon_name : str
        The Pokemon's PokeAPI slug (lowercase, e.g. 'bulbasaur',
        'typhlosion-hisui'). This is the `name` field on the Pokemon
        dataclass, not the display name.

    Returns
    -------
    int
        A prime number derived deterministically from the name.
    """
    digest = hashlib.sha256(pokemon_name.lower().encode("utf-8")).hexdigest()
    seed = int(digest, 16)  # 256-bit integer
    return _next_prime(seed)


# ---------------------------------------------------------------------------
# RSA math helpers
# ---------------------------------------------------------------------------

def _extended_gcd(a: int, b: int) -> tuple[int, int, int]:
    """Extended Euclidean algorithm. Returns (gcd, x, y) where ax + by = gcd."""
    if a == 0:
        return b, 0, 1
    gcd, x1, y1 = _extended_gcd(b % a, a)
    return gcd, y1 - (b // a) * x1, x1


def _mod_inverse(e: int, phi: int) -> int:
    """
    Compute the modular inverse of e mod phi (i.e. d such that e*d ≡ 1 mod phi).

    Raises ValueError if the inverse does not exist (gcd(e, phi) != 1).
    """
    gcd, x, _ = _extended_gcd(e % phi, phi)
    if gcd != 1:
        raise ValueError(
            f"Modular inverse does not exist: gcd({e}, {phi}) = {gcd}. "
            "The chosen public exponent e is not coprime with φ(n). "
            "This should not occur with standard e=65537 — check your primes."
        )
    return x % phi


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------

# Standard RSA public exponent. 65537 (2^16 + 1) is a Fermat prime widely
# used in practice: large enough to resist small-exponent attacks, small
# enough for fast encryption.
PUBLIC_EXPONENT = 65537


def generate_keypair(prime_p: int, prime_q: int) -> KeyPair:
    """
    Generate an RSA keypair from two primes.

    Parameters
    ----------
    prime_p, prime_q : int
        Two distinct primes, typically derived via derive_prime().

    Returns
    -------
    KeyPair
        A matched public/private keypair.

    Raises
    ------
    ValueError
        If p == q, or if gcd(PUBLIC_EXPONENT, φ(n)) != 1.
    """
    if prime_p == prime_q:
        raise ValueError(
            "p and q must be distinct primes. "
            "The two chosen Pokemon must have different names."
        )

    n = prime_p * prime_q
    phi = (prime_p - 1) * (prime_q - 1)
    e = PUBLIC_EXPONENT

    if math.gcd(e, phi) != 1:
        raise ValueError(
            f"Public exponent e={e} is not coprime with φ(n)={phi}. "
            "Try a different pair of Pokemon."
        )

    d = _mod_inverse(e, phi)

    return KeyPair(
        public=PublicKey(n=n, e=e),
        private=PrivateKey(n=n, d=d),
    )


# ---------------------------------------------------------------------------
# Block encoding
# ---------------------------------------------------------------------------

def _block_size(n: int) -> int:
    """
    Compute the plaintext block size in bytes for a given modulus n.

    We use (bit_length // 8) - 1 to ensure each block, when interpreted
    as an integer, is strictly less than n. The -1 provides a safety margin.
    """
    return (n.bit_length() // 8) - 1


def _encode_message(message: str) -> bytes:
    return message.encode("utf-8")


def _decode_message(data: bytes) -> str:
    return data.decode("utf-8")


def _split_blocks(data: bytes, block_size: int) -> list[bytes]:
    """Split bytes into fixed-size chunks (last chunk may be shorter)."""
    return [data[i:i + block_size] for i in range(0, len(data), block_size)]


def _bytes_to_int(b: bytes) -> int:
    return int.from_bytes(b, byteorder="big")


def _int_to_bytes(n: int, length: int) -> bytes:
    return n.to_bytes(length, byteorder="big")


# ---------------------------------------------------------------------------
# Encrypt / Decrypt
# ---------------------------------------------------------------------------

def encrypt(message: str, public_key: PublicKey) -> list[int]:
    """
    Encrypt a plaintext message using an RSA public key.

    The message is UTF-8 encoded, split into byte blocks sized to fit
    within the modulus n, and each block is independently encrypted via
    modular exponentiation: ciphertext = plaintext^e mod n.

    Parameters
    ----------
    message    : str         Plaintext message to encrypt.
    public_key : PublicKey   RSA public key (n, e).

    Returns
    -------
    list[int]
        A list of ciphertext integers, one per plaintext block.
        Preserve this list in full for decryption.
    """
    if not message:
        raise ValueError("Cannot encrypt an empty message.")

    n, e = public_key.n, public_key.e
    bsize = _block_size(n)
    raw_bytes = _encode_message(message)
    blocks = _split_blocks(raw_bytes, bsize)

    ciphertext = []
    for block in blocks:
        m = _bytes_to_int(block)
        if m >= n:
            # Should not occur given correct block sizing, but guard anyway
            raise ValueError(
                f"Block integer {m} >= modulus {n}. "
                "Block size calculation error — please report this."
            )
        c = pow(m, e, n)
        ciphertext.append(c)

    return ciphertext


def decrypt(ciphertext: list[int], private_key: PrivateKey, public_key: PublicKey) -> str:
    """
    Decrypt a ciphertext block list using an RSA private key.

    Each ciphertext integer is decrypted via modular exponentiation:
    plaintext = ciphertext^d mod n, then converted back to bytes and
    reassembled into the original UTF-8 string.

    Parameters
    ----------
    ciphertext  : list[int]    List of encrypted integers from encrypt().
    private_key : PrivateKey   RSA private key (n, d).
    public_key  : PublicKey    RSA public key — needed for block size calculation.

    Returns
    -------
    str
        The decrypted plaintext message.

    Raises
    ------
    ValueError
        If decryption produces bytes that cannot be decoded as UTF-8,
        indicating a key mismatch or corrupted ciphertext.
    """
    if not ciphertext:
        raise ValueError("Ciphertext is empty.")

    n, d = private_key.n, private_key.d
    bsize = _block_size(public_key.n)

    raw_blocks = []
    for i, c in enumerate(ciphertext):
        m = pow(c, d, n)

        # All blocks except the last are exactly bsize bytes.
        # The last block may be shorter — we derive its length from
        # the decrypted integer's actual byte length.
        is_last = (i == len(ciphertext) - 1)
        if is_last:
            # Determine minimum bytes needed to represent m
            byte_length = (m.bit_length() + 7) // 8 if m > 0 else 1
        else:
            byte_length = bsize

        raw_blocks.append(_int_to_bytes(m, byte_length))

    try:
        return _decode_message(b"".join(raw_blocks))
    except UnicodeDecodeError as exc:
        raise ValueError(
            "Decryption produced invalid UTF-8. "
            "This usually means the wrong private key was used, "
            "or the ciphertext is corrupted."
        ) from exc
