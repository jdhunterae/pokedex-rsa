"""
ui/app.py

Flask web interface for Pokedex RSA.

Routes
------
GET  /                      Main UI (redirects to /setup if DB empty)
GET  /setup                 DB initialization page
POST /api/setup/seed        Trigger seeder, stream progress via SSE
GET  /api/setup/status      DB record count (for polling)

POST /api/session/keys      Upload key files to session temp dir
POST /api/session/keygen    Generate new keys, store in session temp dir
DELETE /api/session/keys    Purge session keys and temp dir
GET  /api/session/status    Check whether keys are loaded

POST /api/bundle/count      Count matching Pokemon for a partial bundle
POST /api/bundle/validate   Validate a bundle resolves to exactly one Pokemon

POST /api/encrypt           Encrypt a message with session public key
POST /api/decrypt           Decrypt a message with session private key
"""

from pokedex_rsa.models.pokemon import PokemonDB, DEFAULT_DB_PATH
from pokedex_rsa.models.crypto import PrivateKey
from pokedex_rsa.controllers.encryption_controller import (
    EncryptionController,
    PokedexPublicBundle,
    EncryptedMessage,
    ResolutionError,
    SamePokemonError,
    EmptyDatabaseError,
    ControllerError,
)
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid

from flask import (
    Flask, jsonify, redirect, render_template,
    request, session, url_for
)

# Allow importing from the project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.secret_key = os.environ.get("POKE_RSA_SECRET", os.urandom(32))

DB_PATH = os.path.abspath(DEFAULT_DB_PATH)
SEEDER_PATH = os.path.join(os.path.dirname(
    __file__), "..", "scripts", "seed_db.py")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db_count() -> int:
    """Return the number of Pokemon records in the database, or 0 if missing."""
    if not os.path.exists(DB_PATH):
        return 0
    try:
        with PokemonDB(db_path=DB_PATH) as db:
            return db.count()
    except Exception:
        return 0


def _controller() -> EncryptionController:
    return EncryptionController(db_path=DB_PATH)


def _session_dir() -> str | None:
    """Return the session's temp directory path, or None if not initialised."""
    return session.get("key_dir")


def _ensure_session_dir() -> str:
    """Create a temp directory for this session if one doesn't exist."""
    key_dir = session.get("key_dir")
    if not key_dir or not os.path.isdir(key_dir):
        key_dir = tempfile.mkdtemp(prefix="poke_rsa_")
        session["key_dir"] = key_dir
    return key_dir


def _private_key_path() -> str | None:
    d = _session_dir()
    if not d:
        return None
    p = os.path.join(d, "private.key")
    return p if os.path.exists(p) else None


def _public_key_path() -> str | None:
    d = _session_dir()
    if not d:
        return None
    p = os.path.join(d, "public.json")
    return p if os.path.exists(p) else None


def _load_private_key() -> PrivateKey | None:
    path = _private_key_path()
    if not path:
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        return PrivateKey(n=int(data["n"]), d=int(data["d"]))
    except Exception:
        return None


def _load_public_bundle() -> PokedexPublicBundle | None:
    path = _public_key_path()
    if not path:
        return None
    try:
        with open(path) as f:
            raw = f.read()
        return PokedexPublicBundle.from_json(raw)
    except Exception:
        return None


def _keys_loaded() -> bool:
    return _private_key_path() is not None and _public_key_path() is not None


def _err(message: str, status: int = 400):
    return jsonify({"error": message}), status


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    if _db_count() == 0:
        return redirect(url_for("setup"))
    return render_template("index.html")


@app.route("/setup")
def setup():
    return render_template("setup.html")


# ---------------------------------------------------------------------------
# Setup API
# ---------------------------------------------------------------------------

@app.route("/api/setup/status")
def api_setup_status():
    count = _db_count()
    return jsonify({"count": count, "ready": count > 0})


# Seeder job state — simple in-process store for the single active job
_seed_job = {"running": False, "log": [],
             "done": False, "error": None, "count": 0}


@app.route("/api/setup/seed", methods=["POST"])
def api_setup_seed():
    """
    Start the seeder in a background thread.
    Request body: { "mode": "starters" | "gen" | "full", "gens": [1,2,...] }
    Poll /api/setup/progress for status updates.
    """
    import threading

    global _seed_job
    if _seed_job["running"]:
        return jsonify({"started": False, "error": "Seeder already running."})

    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "starters")
    gens = data.get("gens", [])

    cmd = [sys.executable, SEEDER_PATH]
    if mode == "starters":
        cmd.append("--starters")
    elif mode == "gen" and gens:
        for g in gens:
            cmd += ["--gen", str(g)]

    _seed_job = {"running": True, "log": [
        "Starting seeder..."], "done": False, "error": None, "count": 0}

    def run():
        global _seed_job
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    _seed_job["log"].append(line)
            proc.wait()
            if proc.returncode == 0:
                _seed_job["count"] = _db_count()
                _seed_job["done"] = True
            else:
                _seed_job["error"] = "Seeder exited with an error."
        except Exception as e:
            _seed_job["error"] = str(e)
        finally:
            _seed_job["running"] = False

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"started": True})


@app.route("/api/setup/progress")
def api_setup_progress():
    """Poll for seeder progress. Returns current log lines, done flag, and record count."""
    return jsonify({
        "running": _seed_job["running"],
        "log":     _seed_job["log"],
        "done":    _seed_job["done"],
        "error":   _seed_job["error"],
        "count":   _seed_job["count"],
    })


# ---------------------------------------------------------------------------
# Session / key management API
# ---------------------------------------------------------------------------

@app.route("/api/session/status")
def api_session_status():
    return jsonify({
        "keys_loaded": _keys_loaded(),
        "has_private": _private_key_path() is not None,
        "has_public":  _public_key_path() is not None,
    })


@app.route("/api/session/keys", methods=["POST"])
def api_session_upload_keys():
    """Accept uploaded private.key and/or public.json files."""
    key_dir = _ensure_session_dir()
    saved = []

    if "private_key" in request.files:
        f = request.files["private_key"]
        # Validate it looks like a private key
        try:
            data = json.load(f)
            if "n" not in data or "d" not in data:
                return _err("private_key file must contain 'n' and 'd' fields.")
            with open(os.path.join(key_dir, "private.key"), "w") as out:
                json.dump(data, out)
            saved.append("private_key")
        except Exception as e:
            return _err(f"Could not parse private key: {e}")

    if "public_key" in request.files:
        f = request.files["public_key"]
        try:
            raw = f.read().decode("utf-8")
            bundle = PokedexPublicBundle.from_json(raw)
            with open(os.path.join(key_dir, "public.json"), "w") as out:
                out.write(bundle.to_json())
            saved.append("public_key")
        except Exception as e:
            return _err(f"Could not parse public key: {e}")

    if not saved:
        return _err("No valid key files provided.")

    return jsonify({"saved": saved, "keys_loaded": _keys_loaded()})


@app.route("/api/session/keygen", methods=["POST"])
def api_session_keygen():
    """
    Generate a new keypair and store it in the session temp dir.
    Request body: { "bundle_p": {...} | null, "bundle_q": {...} | null }
    """
    data = request.get_json(silent=True) or {}
    bundle_p = data.get("bundle_p") or None
    bundle_q = data.get("bundle_q") or None
    key_dir = _ensure_session_dir()

    try:
        controller = _controller()
        keypair = controller.generate_keypair(bundle_p, bundle_q)
    except EmptyDatabaseError as e:
        return _err(str(e))
    except ResolutionError as e:
        return _err(str(e))
    except SamePokemonError as e:
        return _err(str(e))
    except ControllerError as e:
        return _err(str(e))

    # Persist to session temp dir
    private_json = json.dumps(
        {"n": keypair.private_key.n, "d": keypair.private_key.d})
    public_json = keypair.public_bundle.to_json()

    with open(os.path.join(key_dir, "private.key"), "w") as f:
        f.write(private_json)
    with open(os.path.join(key_dir, "public.json"), "w") as f:
        f.write(public_json)

    return jsonify({
        "keys_loaded": True,
        "pokemon_p":   str(keypair.pokemon_p),
        "pokemon_q":   str(keypair.pokemon_q),
        "modulus_bits": keypair.public_key.n.bit_length(),
        "public_bundle_inline": json.dumps(json.loads(public_json)),
    })


@app.route("/api/session/keys", methods=["DELETE"])
def api_session_purge_keys():
    """Delete session keys and temp directory."""
    key_dir = _session_dir()
    if key_dir and os.path.isdir(key_dir):
        shutil.rmtree(key_dir, ignore_errors=True)
    session.pop("key_dir", None)
    return jsonify({"keys_loaded": False})


# ---------------------------------------------------------------------------
# Bundle API
# ---------------------------------------------------------------------------

@app.route("/api/bundle/count", methods=["POST"])
def api_bundle_count():
    """
    Return the number of Pokemon matching a partial bundle.
    Request body: { "bundle": {...} }  — bundle may be null/empty for total count.
    """
    data = request.get_json(silent=True) or {}
    bundle = data.get("bundle") or None

    try:
        controller = _controller()
        total = controller.count_candidates()
        matched = controller.count_candidates(bundle)
        return jsonify({"matched": matched, "total": total})
    except ValueError as e:
        return _err(str(e))


@app.route("/api/bundle/validate", methods=["POST"])
def api_bundle_validate():
    """
    Validate a bundle resolves to exactly one Pokemon.
    Request body: { "bundle": {...} }
    """
    data = request.get_json(silent=True) or {}
    bundle = data.get("bundle")

    if not bundle:
        return _err("No bundle provided.")

    try:
        controller = _controller()
        ok, err_msg, pokemon = controller.validate_bundle(bundle)
        if ok:
            return jsonify({"valid": True, "pokemon": str(pokemon)})
        else:
            return jsonify({"valid": False, "error": err_msg})
    except ValueError as e:
        return _err(str(e))


# ---------------------------------------------------------------------------
# Encrypt / Decrypt API
# ---------------------------------------------------------------------------

@app.route("/api/encrypt", methods=["POST"])
def api_encrypt():
    """
    Encrypt a message using the session public key.
    Request body: { "message": "..." }
    """
    if not _keys_loaded():
        return _err("No keys loaded. Generate or upload keys first.", 401)

    data = request.get_json(silent=True) or {}
    message = data.get("message", "")

    if not message.strip():
        return _err("Message cannot be empty.")

    bundle = _load_public_bundle()
    if not bundle:
        return _err("Could not load public key from session.", 500)

    try:
        controller = _controller()
        encrypted = controller.encrypt(message, bundle)
        # Build compact JSON directly from the dataclass fields — no round-trip
        # through json.loads which would lose large integer precision.
        encrypted_compact = json.dumps({
            "ciphertext":    encrypted.ciphertext,
            "public_bundle": {
                "bundle_p": encrypted.public_bundle.bundle_p,
                "bundle_q": encrypted.public_bundle.bundle_q,
                "e":        encrypted.public_bundle.e,
            }
        })
        return jsonify({
            "encrypted_raw":    encrypted_compact,
            "encrypted_inline": encrypted_compact,
            "blocks":           len(encrypted.ciphertext),
        })
    except ResolutionError as e:
        return _err(str(e))
    except ValueError as e:
        return _err(str(e))


@app.route("/api/decrypt", methods=["POST"])
def api_decrypt():
    """
    Decrypt a message using the session private key.
    Request body: { "encrypted": <encrypted JSON object> }
    """
    if not _keys_loaded():
        return _err("No keys loaded. Generate or upload keys first.", 401)

    data = request.get_json(silent=True) or {}
    enc_raw = data.get("encrypted_raw")   # preferred: raw JSON string
    enc_data = data.get("encrypted")       # fallback: parsed object

    if not enc_raw and not enc_data:
        return _err("No encrypted message provided.")

    private_key = _load_private_key()
    if not private_key:
        return _err("Could not load private key from session.", 500)

    try:
        # Use raw string if available to preserve large integer precision.
        # Parsed objects lose precision when JS JSON.parse converts large ints to floats.
        if enc_raw:
            encrypted = EncryptedMessage.from_json(enc_raw)
        else:
            encrypted = EncryptedMessage.from_json(json.dumps(enc_data))
        controller = _controller()
        plaintext = controller.decrypt(encrypted, private_key)
        return jsonify({"plaintext": plaintext})
    except ResolutionError as e:
        return _err(str(e))
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        return _err(str(e))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, port=5000)
