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
    Raised when both prime slots can only resolve to the same Pokemon.
    RSA requires two *distinct* primes — the same Pokemon would produce p == q.
    """

    def __init__(self, pokemon: Pokemon):
        self.pokemon = pokemon
        super().__init__(
            f"Both filters can only select the same Pokemon ({pokemon.display_name}). "
            "RSA requires two distinct Pokemon. "
            "Change at least one filter to include different Pokemon."
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
        # Resolve the candidate pools for both slots upfront so we can check
        # whether a non-colliding pair is even possible before attempting random
        # selection. This avoids silently retrying in an impossible situation.
        pool_p = self._resolver.candidates(bundle_p or {})
        pool_q = self._resolver.candidates(bundle_q or {})

        if not pool_p:
            raise ResolutionError(
                "bundle_p matched no Pokemon in the database.",
                bundle=bundle_p or {},
                cause=NoMatchError(bundle_p or {}),
            )
        if not pool_q:
            raise ResolutionError(
                "bundle_q matched no Pokemon in the database.",
                bundle=bundle_q or {},
                cause=NoMatchError(bundle_q or {}),
            )

        # Check whether a non-colliding pair is possible at all.
        # If both pools contain only one Pokemon and it's the same one,
        # no amount of retrying will help — tell the user immediately.
        names_p = {p.name for p in pool_p}
        names_q = {p.name for p in pool_q}
        if names_p == names_q and len(names_p) == 1:
            raise SamePokemonError(pool_p[0])

        # If the pools overlap but have other options, we can find a valid pair.
        # Pick from each pool ensuring the two selections differ.
        import random as _random
        max_attempts = 50
        pokemon_p = pokemon_q = None
        for _ in range(max_attempts):
            pokemon_p = _random.choice(pool_p)
            pokemon_q = _random.choice(pool_q)
            if pokemon_p.name != pokemon_q.name:
                break
        else:
            # Pools overlap completely — find valid pair exhaustively
            valid_pairs = [
                (a, b) for a in pool_p for b in pool_q if a.name != b.name
            ]
            if not valid_pairs:
                raise SamePokemonError(pool_p[0])
            pokemon_p, pokemon_q = _random.choice(valid_pairs)

        minimal_p = self._build_minimal_bundle(pokemon_p)
        minimal_q = self._build_minimal_bundle(pokemon_q)

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

    def validate_keypair(
        self,
        public_bundle: "PokedexPublicBundle",
        private_key: "PrivateKey",
    ) -> tuple[str, Optional[str], Optional["Pokemon"], Optional["Pokemon"]]:
        """
        Validate that a public bundle and private key form a matching pair.

        Process:
          1. Resolve both Pokemon from the public bundle
          2. Derive primes from their names
          3. Compute n = p × q
          4. Compare with the n stored in the private key

        Returns
        -------
        (status, error_message, pokemon_p, pokemon_q)

        status values:
          'valid'        — keys match; pokemon_p and pokemon_q are populated
          'unresolvable' — one or both Pokemon cannot be resolved from the DB;
                           the public key may reference Pokemon not in the
                           current database (corrupted or needs re-seed)
          'mismatch'     — both Pokemon resolved but n values don't match;
                           the private and public keys are not a pair
        """
        # Step 1: Resolve Pokemon from the public bundle
        try:
            pokemon_p = self._resolve_bundle(
                public_bundle.bundle_p, label="bundle_p")
            pokemon_q = self._resolve_bundle(
                public_bundle.bundle_q, label="bundle_q")
        except ResolutionError:
            return (
                "unresolvable",
                "This public key cannot be validated with the current database. "
                "The data may be corrupted, or you may need to re-seed your database.",
                None,
                None,
            )

        # Step 2: Derive n from the resolved Pokemon
        p = derive_prime(pokemon_p.name)
        q = derive_prime(pokemon_q.name)
        expected_n = p * q

        # Step 3: Compare with the private key's n
        if expected_n != private_key.n:
            return (
                "mismatch",
                "Key mismatch — these keys don't work together. "
                "Purge and re-upload both files.",
                None,
                None,
            )

        return ("valid", None, pokemon_p, pokemon_q)

    def list_candidates(
        self,
        partial_bundle: Optional[dict] = None,
        search: Optional[str] = None,
        limit: int = 20,
    ) -> list:
        """
        Return Pokemon matching a partial bundle, optionally filtered by
        a name search fragment. Results are capped at `limit` for UI performance.

        Parameters
        ----------
        partial_bundle : dict or None
            Any combination of valid fields to filter by.
        search : str or None
            Case-insensitive substring to match against Pokemon names.
        limit : int
            Maximum number of results to return.

        Returns
        -------
        list[Pokemon]
        """
        candidates = self._resolver.candidates(partial_bundle or {})
        if search:
            needle = search.lower().strip()
            candidates = [p for p in candidates if needle in p.name.lower()]
        return candidates[:limit]

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
