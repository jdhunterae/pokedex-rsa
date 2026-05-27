"""
models/resolver.py

Metadata resolver for Pokemon-based key exchange.

The resolver accepts a metadata bundle — a dict of field/value pairs — and
attempts to identify exactly one Pokemon in the local database that matches.
This is the mechanism by which a public key (a metadata puzzle) is converted
back into a Pokemon name, which is then hashed to reconstruct the prime.

Resolution rules:
  - Zero matches  → raises NoMatchError
  - One match     → returns the Pokemon (success)
  - Many matches  → raises AmbiguousMatchError

The sender is responsible for constructing a bundle that uniquely identifies
their chosen Pokemon. The resolver enforces uniqueness on the recipient side.
"""

from __future__ import annotations
from typing import Optional
from .pokemon import Pokemon, PokemonDB


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ResolverError(Exception):
    """Base class for all resolver errors."""


class NoMatchError(ResolverError):
    """Raised when the metadata bundle matches zero Pokemon."""

    def __init__(self, bundle: dict):
        self.bundle = bundle
        super().__init__(
            f"No Pokemon found matching metadata: {bundle}. "
            "Ensure both sender and recipient are using the same database."
        )


class AmbiguousMatchError(ResolverError):
    """Raised when the metadata bundle matches more than one Pokemon."""

    def __init__(self, bundle: dict, matches: list[Pokemon]):
        self.bundle = bundle
        self.matches = matches
        names = ", ".join(str(p.name) for p in matches)
        super().__init__(
            f"Metadata bundle matches {len(matches)} Pokemon ({names}). "
            "Add more metadata fields to uniquely identify the intended Pokemon."
        )


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

class PokemonResolver:
    """
    Resolves a metadata bundle to a unique Pokemon.

    The resolver wraps a PokemonDB and provides two public methods:

      resolve(bundle)         → Pokemon  (raises on 0 or 2+ matches)
      candidates(bundle)      → list[Pokemon]  (raw results, no validation)

    Typical usage in the encryption controller:

        resolver = PokemonResolver()
        pokemon  = resolver.resolve({"type_primary": "fire", "generation": 2})
        # → Cyndaquil (if it's the only fire-type Gen 2 in the DB)

    The resolver does not modify the database and holds no state beyond the
    db_path. It is safe to reuse across multiple resolve() calls.
    """

    def __init__(self, db_path: Optional[str] = None):
        self._db_kwargs = {"db_path": db_path} if db_path else {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, bundle: dict) -> Pokemon:
        """
        Resolve a metadata bundle to exactly one Pokemon.

        Parameters
        ----------
        bundle : dict
            A dict of field/value pairs to match against the database.
            Any field accepted by PokemonDB.find_by() is valid:
                id, form, type_primary, type_secondary, height, weight,
                base_stat_total, generation, color

        Returns
        -------
        Pokemon
            The single Pokemon that matches all fields in the bundle.

        Raises
        ------
        NoMatchError
            If no Pokemon matches the bundle.
        AmbiguousMatchError
            If more than one Pokemon matches the bundle.
        ValueError
            If the bundle contains invalid field names (propagated from DB).
        """
        matches = self.candidates(bundle)

        if len(matches) == 0:
            raise NoMatchError(bundle)
        if len(matches) > 1:
            raise AmbiguousMatchError(bundle, matches)

        return matches[0]

    def candidates(self, bundle: dict) -> list[Pokemon]:
        """
        Return all Pokemon matching the metadata bundle without validation.

        Useful for building public keys — the sender can call candidates()
        to check how many Pokemon a given bundle matches before committing
        to it. A well-formed public key should produce exactly one candidate.

        Returns an empty list if no Pokemon match.
        """
        with PokemonDB(**self._db_kwargs) as db:
            return db.find_by(**bundle)

    def is_unique(self, bundle: dict) -> bool:
        """
        Return True if the bundle resolves to exactly one Pokemon.
        Convenience method for key generation validation.
        """
        return len(self.candidates(bundle)) == 1

    def suggest_disambiguating_fields(
        self, bundle: dict, matches: list[Pokemon]
    ) -> list[str]:
        """
        Given an ambiguous bundle and its current matches, return a list of
        field names that differ across the matched Pokemon — i.e. fields that
        could be added to the bundle to narrow it down.

        This is a helper for the key generation process: if the sender's
        initial bundle is ambiguous, this tells them which additional fields
        to include.

        Example:
            bundle  = {"type_primary": "fire", "generation": 1}
            matches = [Charmander, Charmeleon, Charizard]
            → suggests ["height", "weight", "base_stat_total", "color"]
              (since those differ across the three)
        """
        if len(matches) <= 1:
            return []

        CANDIDATE_FIELDS = [
            "type_secondary", "height", "weight",
            "base_stat_total", "color", "form", "id"
        ]

        # Fields already in the bundle don't need to be suggested
        already_used = set(bundle.keys())

        disambiguating = []
        for field in CANDIDATE_FIELDS:
            if field in already_used:
                continue
            values = {getattr(p, field) for p in matches}
            if len(values) > 1:
                disambiguating.append(field)

        return disambiguating
