"""
controllers/encryption_controller.py

Orchestrates the full Pokedex RSA pipeline.

This controller is the single point of contact for the CLI and UI layers. It
wires together the data layer (PokemonDB, PokemonResolver) and the crypto layer
(derive_prime, generate_keypair, encrypt, decrypt) into coherent operations.

Key generation modes
--------------------
generate_keypair() now supports three modes per prime slot:

  Exact bundle   — bundle resolves to exactly one Pokemon (original behavior)
  Partial bundle — bundle matches multiple Pokemon; one is chosen at random
  No bundle      — None passed; one Pokemon chosen at random from entire DB

In all cases the returned PokedexKeypair contains auto-constructed minimal
bundles that uniquely identify the chosen Pokemon, so the public key is always
well-formed regardless of how much (or how little) the caller specified.

New public methods
------------------
  count_candidates(partial_bundle)  — count matching Pokemon without resolving
  random_pokemon(partial_bundle)    — pick one Pokemon at random from a pool
"""

from __future__ import annotations
import json
import random
from dataclasses import dataclass, asdict
from typing import Optional

from ..models.pokemon import Pokemon, PokemonDB
from ..models.resolver import PokemonResolver, ResolverError, AmbiguousMatchError, NoMatchError
from ..models.crypto import (
    derive_prime,
    generate_keypair,
    encrypt as rsa_encrypt,
    decrypt as rsa_decrypt,
    KeyPair,
    PublicKey,
    PrivateKey,
)


# ---------------------------------------------------------------------------
# Controller-level exceptions
# ---------------------------------------------------------------------------

class ControllerError(Exception):
    """Base class for controller-level errors."""


class ResolutionError(ControllerError):
    """
    Raised when a metadata bundle cannot be resolved to a unique Pokemon.
    Wraps ResolverError with additional context about which bundle failed.
    """

    def __init__(self, message: str, bundle: dict, cause: ResolverError):
        self.bundle = bundle
        self.cause = cause
        super().__init__(message)


class SamePokemonError(ControllerError):
    """
    Raised when both prime slots resolve to the same Pokemon.
    RSA requires two *distinct* primes — the same Pokemon would produce p == q.
    """

    def __init__(self, pokemon: Pokemon):
        self.pokemon = pokemon
        super().__init__(
            f"Both slots resolved to the same Pokemon ({pokemon.name}). "
            "Each slot must identify a different Pokemon."
        )


class EmptyDatabaseError(ControllerError):
    """Raised when the database contains no Pokemon records."""

    def __init__(self):
        super().__init__(
            "The Pokemon database is empty. "
            "Run scripts/seed_db.py to populate it before generating keys."
        )


# ---------------------------------------------------------------------------
# Transfer objects
# ---------------------------------------------------------------------------

@dataclass
class PokedexPublicBundle:
    """
    The shareable public key — two metadata bundles that together identify
    the Pokemon pair used to generate the RSA keypair.

    Attributes
    ----------
    bundle_p : dict   Metadata identifying Pokemon p
    bundle_q : dict   Metadata identifying Pokemon q
    e        : int    RSA public exponent (always 65537; included for completeness)
    """
    bundle_p: dict
    bundle_q: dict
    e:        int = 65537

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "PokedexPublicBundle":
        data = json.loads(raw)
        return cls(
            bundle_p=data["bundle_p"],
            bundle_q=data["bundle_q"],
            e=data.get("e", 65537),
        )


@dataclass
class PokedexKeypair:
    """
    The full output of key generation.

    Attributes
    ----------
    rsa_keypair   : KeyPair              Raw RSA keys (public + private)
    public_bundle : PokedexPublicBundle  The shareable metadata public key
    pokemon_p     : Pokemon              The Pokemon that produced prime p
    pokemon_q     : Pokemon              The Pokemon that produced prime q
    """
    rsa_keypair:   KeyPair
    public_bundle: PokedexPublicBundle
    pokemon_p:     Pokemon
    pokemon_q:     Pokemon

    @property
    def public_key(self) -> PublicKey:
        return self.rsa_keypair.public

    @property
    def private_key(self) -> PrivateKey:
        return self.rsa_keypair.private


@dataclass
class EncryptedMessage:
    """
    A fully self-contained encrypted message.

    Attributes
    ----------
    ciphertext    : list[int]            RSA-encrypted integer blocks
    public_bundle : PokedexPublicBundle  Metadata public key (for key reconstruction)
    """
    ciphertext:    list[int]
    public_bundle: PokedexPublicBundle

    def to_json(self) -> str:
        return json.dumps({
            "ciphertext":    self.ciphertext,
            "public_bundle": asdict(self.public_bundle),
        }, indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "EncryptedMessage":
        data = json.loads(raw)
        return cls(
            ciphertext=data["ciphertext"],
            public_bundle=PokedexPublicBundle(
                bundle_p=data["public_bundle"]["bundle_p"],
                bundle_q=data["public_bundle"]["bundle_q"],
                e=data["public_bundle"].get("e", 65537),
            ),
        )


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

# Fields tried in order when auto-constructing a minimal unique bundle.
# Ordered from most to least distinctive to minimise the number of fields
# needed to achieve uniqueness.
_BUNDLE_FIELD_PRIORITY = [
    "base_stat_total",
    "weight",
    "height",
    "type_secondary",
    "color",
    "generation",
    "type_primary",
    "form",
    "id",
]


class EncryptionController:
    """
    Orchestrates the full Pokedex RSA pipeline.

    Parameters
    ----------
    db_path : str, optional
        Path to the local SQLite database. Defaults to the standard location
        at data/pokemon.db relative to the project root.
    """

    def __init__(self, db_path: Optional[str] = None):
        self._resolver = PokemonResolver(db_path=db_path)
        self._db_path = db_path

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_bundle(self, bundle: dict, label: str = "bundle") -> Pokemon:
        """Resolve a bundle to exactly one Pokemon, wrapping errors with context."""
        try:
            return self._resolver.resolve(bundle)
        except NoMatchError as e:
            raise ResolutionError(
                f"The {label} did not match any Pokemon in the database. "
                f"Check your metadata fields and values. (bundle={bundle})",
                bundle=bundle,
                cause=e,
            ) from e
        except AmbiguousMatchError as e:
            suggestions = self._resolver.suggest_disambiguating_fields(
                bundle, e.matches)
            hint = (
                f" Try adding: {suggestions}." if suggestions
                else " No obvious disambiguating fields found — try more specific values."
            )
            raise ResolutionError(
                f"The {label} matched {len(e.matches)} Pokemon. "
                f"Add more fields to narrow it down.{hint} (bundle={bundle})",
                bundle=bundle,
                cause=e,
            ) from e

    def _reconstruct_public_key(self, public_bundle: PokedexPublicBundle) -> PublicKey:
        """Reconstruct the RSA PublicKey from a PokedexPublicBundle."""
        pokemon_p = self._resolve_bundle(
            public_bundle.bundle_p, label="bundle_p")
        pokemon_q = self._resolve_bundle(
            public_bundle.bundle_q, label="bundle_q")
        p = derive_prime(pokemon_p.name)
        q = derive_prime(pokemon_q.name)
        keypair = generate_keypair(p, q)
        return keypair.public

    def _random_pokemon(self, partial_bundle: Optional[dict] = None) -> Pokemon:
        """
        Select one Pokemon at random from the pool matching partial_bundle.
        If partial_bundle is None or empty, selects from the entire database.

        Raises EmptyDatabaseError if the pool is empty.
        """
        pool = self._resolver.candidates(partial_bundle or {})
        if not pool:
            if partial_bundle:
                raise ResolutionError(
                    f"No Pokemon matched the filter bundle {partial_bundle}. "
                    "Try fewer or different filter fields.",
                    bundle=partial_bundle or {},
                    cause=NoMatchError(partial_bundle or {}),
                )
            raise EmptyDatabaseError()
        return random.choice(pool)

    def _select_pokemon(
        self,
        bundle: Optional[dict],
        label: str,
    ) -> tuple[Pokemon, dict]:
        """
        Resolve a bundle to a single Pokemon using the appropriate strategy:

          None or {}  → random from entire DB
          partial     → random from matching pool
          exact       → resolve directly (existing behavior)

        Returns (pokemon, final_bundle) where final_bundle is the auto-constructed
        minimal unique bundle used as the public key component.
        """
        if not bundle:
            pokemon = self._random_pokemon()
        else:
            candidates = self._resolver.candidates(bundle)
            if len(candidates) == 0:
                raise ResolutionError(
                    f"The {label} did not match any Pokemon in the database.",
                    bundle=bundle,
                    cause=NoMatchError(bundle),
                )
            elif len(candidates) == 1:
                # Exact match — use as-is
                pokemon = candidates[0]
            else:
                # Partial match — pick randomly from pool
                pokemon = random.choice(candidates)

        # Always auto-construct the minimal unique bundle for the public key
        minimal_bundle = self._build_minimal_bundle(pokemon)
        return pokemon, minimal_bundle

    def _build_minimal_bundle(self, pokemon: Pokemon) -> dict:
        """
        Auto-construct the tightest metadata bundle that uniquely identifies
        a Pokemon in the current database.

        Tries fields in order of distinctiveness (_BUNDLE_FIELD_PRIORITY),
        adding one field at a time until the bundle resolves to exactly one
        Pokemon. Falls back to including (id, form) which always guarantees
        uniqueness.

        This ensures the public key is always well-formed regardless of how
        the Pokemon was selected (random, partial filter, or exact bundle).
        """
        bundle: dict = {}

        for field_name in _BUNDLE_FIELD_PRIORITY:
            value = getattr(pokemon, field_name)
            bundle[field_name] = value
            candidates = self._resolver.candidates(bundle)
            if len(candidates) == 1:
                return bundle

        # Nuclear fallback — (id, form) is always unique
        return {"id": pokemon.id, "form": pokemon.form}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_keypair(
        self,
        bundle_p: Optional[dict] = None,
        bundle_q: Optional[dict] = None,
    ) -> PokedexKeypair:
        """
        Generate a Pokedex RSA keypair.

        Supports three modes per prime slot (p and q independently):

          Exact bundle   — dict resolving to exactly one Pokemon
          Partial bundle — dict matching multiple Pokemon; one chosen at random
          None / {}      — one Pokemon chosen at random from the entire database

        In all cases the public key bundles in the returned PokedexKeypair are
        auto-constructed minimal bundles that uniquely identify each Pokemon,
        regardless of how much or how little the caller specified.

        Parameters
        ----------
        bundle_p : dict or None   Filter/bundle for the first Pokemon (prime p)
        bundle_q : dict or None   Filter/bundle for the second Pokemon (prime q)

        Returns
        -------
        PokedexKeypair

        Raises
        ------
        ResolutionError    If a bundle matches no Pokemon.
        SamePokemonError   If both slots resolve to the same Pokemon.
        EmptyDatabaseError If the database has no records.
        """
        pokemon_p, minimal_p = self._select_pokemon(bundle_p, label="bundle_p")

        # Retry loop: if random selection produces the same Pokemon for both
        # slots, retry up to 10 times before raising.
        max_attempts = 10
        for attempt in range(max_attempts):
            pokemon_q, minimal_q = self._select_pokemon(
                bundle_q, label="bundle_q")
            if pokemon_q.name != pokemon_p.name:
                break
        else:
            raise SamePokemonError(pokemon_p)

        p = derive_prime(pokemon_p.name)
        q = derive_prime(pokemon_q.name)

        rsa_keypair = generate_keypair(p, q)

        public_bundle = PokedexPublicBundle(
            bundle_p=minimal_p,
            bundle_q=minimal_q,
            e=rsa_keypair.public.e,
        )

        return PokedexKeypair(
            rsa_keypair=rsa_keypair,
            public_bundle=public_bundle,
            pokemon_p=pokemon_p,
            pokemon_q=pokemon_q,
        )

    def encrypt(
        self,
        message: str,
        public_bundle: PokedexPublicBundle,
    ) -> EncryptedMessage:
        """Encrypt a plaintext message using a PokedexPublicBundle."""
        public_key = self._reconstruct_public_key(public_bundle)
        ciphertext = rsa_encrypt(message, public_key)
        return EncryptedMessage(
            ciphertext=ciphertext,
            public_bundle=public_bundle,
        )

    def decrypt(
        self,
        encrypted_message: EncryptedMessage,
        private_key: PrivateKey,
    ) -> str:
        """Decrypt an EncryptedMessage using an RSA private key."""
        public_key = self._reconstruct_public_key(
            encrypted_message.public_bundle)
        return rsa_decrypt(
            encrypted_message.ciphertext,
            private_key,
            public_key,
        )

    def validate_bundle(self, bundle: dict) -> tuple[bool, Optional[str], Optional[Pokemon]]:
        """
        Validate that a metadata bundle resolves to exactly one Pokemon.

        Returns
        -------
        (True,  None,          pokemon)   if the bundle uniquely resolves
        (False, error_message, None)      if zero or multiple matches
        """
        try:
            pokemon = self._resolve_bundle(bundle)
            return True, None, pokemon
        except ResolutionError as e:
            return False, str(e), None

    def count_candidates(self, partial_bundle: Optional[dict] = None) -> int:
        """
        Return the number of Pokemon matching a partial bundle.

        With no bundle (or empty dict), returns the total count of all Pokemon
        in the database. Useful for the UI filter counter.

        Parameters
        ----------
        partial_bundle : dict or None
            Any combination of valid fields. Does not need to be unique.

        Returns
        -------
        int   Number of matching Pokemon.
        """
        return len(self._resolver.candidates(partial_bundle or {}))

    def random_pokemon(self, partial_bundle: Optional[dict] = None) -> Pokemon:
        """
        Select one Pokemon at random from the pool matching partial_bundle.
        Public wrapper around _random_pokemon for external callers (e.g. UI).
        """
        return self._random_pokemon(partial_bundle)
