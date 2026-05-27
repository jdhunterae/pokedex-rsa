"""
controllers/encryption_controller.py

Orchestrates the full Pokedex RSA pipeline.

This controller is the single point of contact for the CLI layer. It wires
together the data layer (PokemonDB, PokemonResolver) and the crypto layer
(derive_prime, generate_keypair, encrypt, decrypt) into three coherent
operations:

  EncryptionController.generate_keypair(bundle_p, bundle_q)
      Resolve two metadata bundles → two Pokemon → two primes → RSA keypair.
      Returns a PokedexKeypair containing the RSA keys and the bundles that
      produced them (these bundles ARE the shareable public key).

  EncryptionController.encrypt(message, public_bundle)
      Resolve a PokedexPublicBundle → reconstruct the RSA public key →
      encrypt the message. Returns a EncryptedMessage ready to transmit.

  EncryptionController.decrypt(encrypted_message, private_key)
      Use the RSA private key and the public bundle embedded in the
      EncryptedMessage to decrypt and return the plaintext.

Data flow
---------
Keygen:
    bundle_p  ──resolver──▶  pokemon_p  ──derive_prime──▶  p  ─┐
    bundle_q  ──resolver──▶  pokemon_q  ──derive_prime──▶  q  ─┴─▶  KeyPair

Encrypt:
    public_bundle  ──resolver──▶  (pokemon_p, pokemon_q)
                   ──derive_prime──▶  (p, q)
                   ──generate_keypair──▶  PublicKey
                   ──encrypt──▶  ciphertext blocks

Decrypt:
    private_key + public_bundle  ──resolver──▶  PublicKey (for block sizing)
                                 ──decrypt──▶  plaintext
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
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
    Raised when both metadata bundles resolve to the same Pokemon.
    RSA requires two *distinct* primes — the same Pokemon would produce p == q.
    """

    def __init__(self, pokemon: Pokemon):
        self.pokemon = pokemon
        super().__init__(
            f"Both metadata bundles resolved to the same Pokemon ({pokemon.name}). "
            "Each bundle must identify a different Pokemon."
        )


# ---------------------------------------------------------------------------
# Transfer objects
# ---------------------------------------------------------------------------

@dataclass
class PokedexPublicBundle:
    """
    The shareable public key — two metadata bundles that together identify
    the Pokemon pair used to generate the RSA keypair.

    This is what the sender transmits to the recipient. The recipient feeds
    each bundle into the resolver to reconstruct the RSA public key and
    (indirectly) the private key primes for decryption.

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

    Contains both the RSA keypair and the public bundle. The sender keeps
    the private key secret and shares the public bundle with the recipient.

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

    Contains the ciphertext blocks AND the public bundle needed to
    reconstruct the RSA public key for decryption block-size calculation.
    The recipient needs this object plus the private key to decrypt.

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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_bundle(self, bundle: dict, label: str = "bundle") -> Pokemon:
        """
        Resolve a metadata bundle to a unique Pokemon.
        Wraps resolver errors with controller-level context.
        """
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
        """
        Reconstruct the RSA PublicKey from a PokedexPublicBundle.
        Used during both encrypt and decrypt to ensure consistent block sizing.
        """
        pokemon_p = self._resolve_bundle(
            public_bundle.bundle_p, label="bundle_p")
        pokemon_q = self._resolve_bundle(
            public_bundle.bundle_q, label="bundle_q")
        p = derive_prime(pokemon_p.name)
        q = derive_prime(pokemon_q.name)
        keypair = generate_keypair(p, q)
        return keypair.public

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_keypair(
        self,
        bundle_p: dict,
        bundle_q: dict,
    ) -> PokedexKeypair:
        """
        Generate a Pokedex RSA keypair from two metadata bundles.

        Each bundle is resolved to a unique Pokemon. The Pokemon names are
        hashed to derive primes, which are used to generate the RSA keypair.
        The bundles themselves become the shareable public key.

        Parameters
        ----------
        bundle_p : dict   Metadata bundle identifying the first Pokemon (prime p)
        bundle_q : dict   Metadata bundle identifying the second Pokemon (prime q)

        Returns
        -------
        PokedexKeypair
            Contains the RSA keypair, the public bundle, and both Pokemon.

        Raises
        ------
        ResolutionError   If either bundle fails to resolve to a unique Pokemon.
        SamePokemonError  If both bundles resolve to the same Pokemon.
        """
        pokemon_p = self._resolve_bundle(bundle_p, label="bundle_p")
        pokemon_q = self._resolve_bundle(bundle_q, label="bundle_q")

        if pokemon_p.name == pokemon_q.name:
            raise SamePokemonError(pokemon_p)

        p = derive_prime(pokemon_p.name)
        q = derive_prime(pokemon_q.name)

        rsa_keypair = generate_keypair(p, q)

        public_bundle = PokedexPublicBundle(
            bundle_p=bundle_p,
            bundle_q=bundle_q,
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
        """
        Encrypt a plaintext message using a PokedexPublicBundle.

        Reconstructs the RSA public key from the bundle, then encrypts
        the message into ciphertext blocks.

        Parameters
        ----------
        message       : str                  Plaintext to encrypt.
        public_bundle : PokedexPublicBundle  The sender's shareable public key.

        Returns
        -------
        EncryptedMessage
            Contains the ciphertext blocks and the public bundle.

        Raises
        ------
        ResolutionError   If the bundle fails to resolve.
        ValueError        If the message is empty.
        """
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
        """
        Decrypt an EncryptedMessage using an RSA private key.

        Reconstructs the RSA public key from the embedded bundle (needed for
        block size calculation), then decrypts the ciphertext blocks.

        Parameters
        ----------
        encrypted_message : EncryptedMessage   The message to decrypt.
        private_key       : PrivateKey         The RSA private key.

        Returns
        -------
        str
            The decrypted plaintext message.

        Raises
        ------
        ResolutionError   If the embedded public bundle fails to resolve.
        ValueError        If decryption fails (wrong key or corrupted ciphertext).
        """
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

        Useful for interactive key construction — the sender can validate
        each bundle before committing to a keypair.

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
