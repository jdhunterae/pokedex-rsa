"""
views/cli.py

Command-line interface for Pokedex RSA.

Commands
--------
  keygen   Generate a keypair from two Pokemon metadata bundles
  encrypt  Encrypt a message using a public key bundle
  decrypt  Decrypt a message using a private key

Output modes
------------
  default    Writes key/message files to disk. Prints a brief confirmation.
  --verbose  Writes files AND prints full content to terminal.
  --fileless Prints full content to terminal only. No files written.
             (--fileless and --verbose are mutually exclusive)

File I/O
--------
  keygen  → private.key, public.json
  encrypt → encrypted.json  (reads public.json by default)
  decrypt → plaintext.txt   (reads encrypted.json + private.key by default)

In --fileless mode all input is passed as inline JSON strings and all
output is printed to stdout, making the output of one command directly
pasteable as the input to the next.
"""

from pokedex_rsa.models.crypto import PrivateKey
from pokedex_rsa.controllers.encryption_controller import (
    EncryptionController,
    PokedexPublicBundle,
    EncryptedMessage,
    ResolutionError,
    SamePokemonError,
    ControllerError,
)
import json
import os
import sys
import click

# Allow running as `python -m pokedex_rsa.views.cli` from the project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _controller() -> EncryptionController:
    return EncryptionController()


def _err(message: str) -> None:
    """Print a styled error and exit."""
    click.echo(click.style(f"\n✗ {message}", fg="red"), err=True)
    sys.exit(1)


def _ok(message: str) -> None:
    click.echo(click.style(f"✓ {message}", fg="green"))


def _info(label: str, value: str) -> None:
    click.echo(f"  {click.style(label, bold=True)}: {value}")


def _section(title: str) -> None:
    click.echo(f"\n{click.style(title, bold=True, underline=True)}")


def _parse_bundle(raw: str, label: str) -> dict:
    """Parse a JSON string into a metadata bundle dict."""
    try:
        bundle = json.loads(raw)
        if not isinstance(bundle, dict):
            _err(f"{label} must be a JSON object, got {type(bundle).__name__}.")
        return bundle
    except json.JSONDecodeError as e:
        _err(f"Could not parse {label} as JSON: {e}")


def _parse_private_key(raw: str) -> PrivateKey:
    """Parse a JSON string into a PrivateKey."""
    try:
        data = json.loads(raw)
        return PrivateKey(n=int(data["n"]), d=int(data["d"]))
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        _err(f"Could not parse private key: {e}")


def _private_key_to_json(private_key: PrivateKey) -> str:
    """Serialize a PrivateKey to a condensed JSON string."""
    return json.dumps({"n": private_key.n, "d": private_key.d})


def _check_fileless_verbose(fileless: bool, verbose: bool) -> None:
    if fileless and verbose:
        _err("--fileless and --verbose are mutually exclusive.")


def _write_file(path: str, content: str, label: str) -> None:
    """Write content to a file, confirming on success."""
    try:
        with open(path, "w") as f:
            f.write(content)
        _ok(f"{label} → {path}")
    except OSError as e:
        _err(f"Could not write {path}: {e}")


def _read_file(path: str, label: str) -> str:
    """Read a file and return its content."""
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        _err(f"{label} not found at '{path}'. Run keygen first, or pass --{label.lower().replace(' ', '-')} directly.")
    except OSError as e:
        _err(f"Could not read {path}: {e}")


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option("0.1.0", prog_name="poke-rsa")
def cli():
    """
    Pokedex RSA — Pokemon-powered RSA encryption.

    Encrypt messages using Pokemon metadata as the public key.
    Each keypair is identified by two Pokemon whose names are hashed
    to derive RSA primes. Share the metadata puzzle, not the key.

    \b
    Quickstart (file mode):
      poke-rsa keygen --bundle-p '{"type_primary":"grass"}' \\
                      --bundle-q '{"type_primary":"fire","generation":1}'
      poke-rsa encrypt --message "Hello, Trainer!"
      poke-rsa decrypt

    \b
    Quickstart (fileless mode):
      poke-rsa keygen --fileless --bundle-p '...' --bundle-q '...'
      poke-rsa encrypt --fileless --message "Hello!" --public-key '<paste>'
      poke-rsa decrypt --fileless --encrypted '<paste>' --private-key '<paste>'
    """


# ---------------------------------------------------------------------------
# keygen
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--bundle-p", required=True,
    help='JSON metadata bundle identifying the first Pokemon. e.g. \'{"type_primary":"fire","generation":1}\''
)
@click.option(
    "--bundle-q", required=True,
    help='JSON metadata bundle identifying the second Pokemon.'
)
@click.option(
    "--private-key-out", default="private.key", show_default=True,
    help="Output path for the private key file."
)
@click.option(
    "--public-key-out", default="public.json", show_default=True,
    help="Output path for the public key file."
)
@click.option(
    "--verbose", is_flag=True,
    help="Write files and also print full key content to terminal."
)
@click.option(
    "--fileless", is_flag=True,
    help="Print keys to terminal only. No files written."
)
def keygen(bundle_p, bundle_q, private_key_out, public_key_out, verbose, fileless):
    """Generate a keypair from two Pokemon metadata bundles."""
    _check_fileless_verbose(fileless, verbose)

    bp = _parse_bundle(bundle_p, "--bundle-p")
    bq = _parse_bundle(bundle_q, "--bundle-q")

    # Validate bundles before doing any crypto work
    controller = _controller()
    ok_p, err_p, pokemon_p = controller.validate_bundle(bp)
    if not ok_p:
        _err(f"--bundle-p: {err_p}")

    ok_q, err_q, pokemon_q = controller.validate_bundle(bq)
    if not ok_q:
        _err(f"--bundle-q: {err_q}")

    if pokemon_p.name == pokemon_q.name:
        _err(
            f"Both bundles resolve to the same Pokemon ({pokemon_p.name}). Use two different Pokemon.")

    click.echo(f"\nGenerating keypair from {click.style(pokemon_p.display_name, bold=True)} "
               f"× {click.style(pokemon_q.display_name, bold=True)}...")

    try:
        keypair = controller.generate_keypair(bp, bq)
    except (ResolutionError, SamePokemonError, ControllerError) as e:
        _err(str(e))

    private_json = _private_key_to_json(keypair.private_key)
    public_json = keypair.public_bundle.to_json()
    public_inline = json.dumps(json.loads(
        public_json))  # condensed single-line

    # --- File output ---
    if not fileless:
        click.echo()
        _write_file(private_key_out, private_json, "Private key")
        _write_file(public_key_out, public_json, "Public key ")

    # --- Terminal output ---
    if verbose or fileless:
        _section("Private Key (keep secret)")
        click.echo(f"  {private_json}")

        _section("Public Key (share with recipient)")
        click.echo(f"  {public_inline}")

    # Always show the resolved Pokemon for transparency
    _section("Key Summary")
    _info("Pokemon P", str(keypair.pokemon_p))
    _info("Pokemon Q", str(keypair.pokemon_q))
    _info("Modulus size", f"{keypair.public_key.n.bit_length()} bits")

    click.echo()


# ---------------------------------------------------------------------------
# encrypt
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--message", required=True,
    help="The plaintext message to encrypt."
)
@click.option(
    "--public-key",
    help="Public key JSON string (fileless mode). Omit to read from --public-key-file."
)
@click.option(
    "--public-key-file", default="public.json", show_default=True,
    help="Path to the public key JSON file."
)
@click.option(
    "--out", default="encrypted.json", show_default=True,
    help="Output path for the encrypted message file."
)
@click.option(
    "--verbose", is_flag=True,
    help="Write file and also print ciphertext to terminal."
)
@click.option(
    "--fileless", is_flag=True,
    help="Print encrypted output to terminal only. No files written."
)
def encrypt(message, public_key, public_key_file, out, verbose, fileless):
    """Encrypt a message using a public key bundle."""
    _check_fileless_verbose(fileless, verbose)

    if not message.strip():
        _err("Message cannot be empty.")

    # Resolve public key source
    if fileless:
        if not public_key:
            _err("--fileless mode requires --public-key <JSON string>.")
        raw_public = public_key
    else:
        raw_public = public_key if public_key else _read_file(
            public_key_file, "Public key file")

    try:
        bundle = PokedexPublicBundle.from_json(raw_public)
    except (json.JSONDecodeError, KeyError) as e:
        _err(f"Could not parse public key: {e}")

    click.echo("\nEncrypting message...")

    try:
        controller = _controller()
        encrypted = controller.encrypt(message, bundle)
    except ResolutionError as e:
        _err(str(e))
    except ValueError as e:
        _err(str(e))

    encrypted_json = encrypted.to_json()
    encrypted_inline = json.dumps(json.loads(encrypted_json))

    # --- File output ---
    if not fileless:
        click.echo()
        _write_file(out, encrypted_json, "Encrypted message")

    # --- Terminal output ---
    if verbose or fileless:
        _section("Encrypted Message")
        click.echo(f"  {encrypted_inline}")

    _section("Encryption Summary")
    _info("Blocks", str(len(encrypted.ciphertext)))
    _info("Message length", f"{len(message)} characters")

    click.echo()


# ---------------------------------------------------------------------------
# decrypt
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--private-key",
    help="Private key JSON string (fileless mode). Omit to read from --private-key-file."
)
@click.option(
    "--private-key-file", default="private.key", show_default=True,
    help="Path to the private key file."
)
@click.option(
    "--encrypted",
    help="Encrypted message JSON string (fileless mode). Omit to read from --encrypted-file."
)
@click.option(
    "--encrypted-file", default="encrypted.json", show_default=True,
    help="Path to the encrypted message JSON file."
)
@click.option(
    "--out", default="plaintext.txt", show_default=True,
    help="Output path for the decrypted plaintext file."
)
@click.option(
    "--verbose", is_flag=True,
    help="Write file and also print plaintext to terminal."
)
@click.option(
    "--fileless", is_flag=True,
    help="Print decrypted output to terminal only. No files written."
)
def decrypt(private_key, private_key_file, encrypted, encrypted_file, out, verbose, fileless):
    """Decrypt a message using a private key."""
    _check_fileless_verbose(fileless, verbose)

    # Resolve private key source
    if fileless:
        if not private_key:
            _err("--fileless mode requires --private-key <JSON string>.")
        if not encrypted:
            _err("--fileless mode requires --encrypted <JSON string>.")
        raw_private = private_key
        raw_encrypted = encrypted
    else:
        raw_private = private_key if private_key else _read_file(
            private_key_file, "Private key file")
        raw_encrypted = encrypted if encrypted else _read_file(
            encrypted_file,   "Encrypted message file")

    private_key_obj = _parse_private_key(raw_private)

    try:
        encrypted_msg = EncryptedMessage.from_json(raw_encrypted)
    except (json.JSONDecodeError, KeyError) as e:
        _err(f"Could not parse encrypted message: {e}")

    click.echo("\nDecrypting message...")

    try:
        controller = _controller()
        plaintext = controller.decrypt(encrypted_msg, private_key_obj)
    except ResolutionError as e:
        _err(str(e))
    except ValueError as e:
        _err(str(e))

    # --- File output ---
    if not fileless:
        click.echo()
        _write_file(out, plaintext, "Decrypted message")

    # --- Terminal output ---
    if verbose or fileless:
        _section("Decrypted Message")
        click.echo(f"\n  {plaintext}\n")
    else:
        # Always at least confirm success with a preview
        preview = plaintext[:60] + ("..." if len(plaintext) > 60 else "")
        click.echo()
        _ok(f'Decrypted: "{preview}"')

    click.echo()


# ---------------------------------------------------------------------------
# validate (bonus utility command)
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--bundle", required=True,
    help="JSON metadata bundle to validate."
)
def validate(bundle):
    """
    Check whether a metadata bundle uniquely identifies a Pokemon.

    Useful for building bundles interactively before running keygen.
    """
    b = _parse_bundle(bundle, "--bundle")
    controller = _controller()

    try:
        ok, err, pokemon = controller.validate_bundle(b)
    except ValueError as e:
        _err(str(e))

    if ok:
        _ok(f"Bundle resolves to: {pokemon}")
    else:
        click.echo(click.style(f"\n✗ {err}", fg="yellow"), err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()
