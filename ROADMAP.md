# Pokedex RSA — Project Roadmap

## Branching Strategy

```
main                  # stable, working code only
└── develop           # integration branch, merges into main per phase
    ├── phase/1-data-layer
    ├── phase/2-crypto
    ├── phase/3-controller
    ├── phase/4-cli
    ├── phase/5-polish
    └── phase/6-ui
```

Each phase branch cuts from `develop`, gets merged back into `develop` when complete.
`develop` merges into `main` at the end of each phase once verified stable.
`main` always represents a working, if incomplete, state of the project.

> The seeder script and project scaffolding (setup.sh, .gitignore, README, requirements.txt) are committed directly to `main` before cutting `develop`, as they are setup infrastructure rather than application code.

---

## Phases

### Phase 0 — Scaffolding `[complete]`
>
> Committed directly to `main`

- [x] Project directory structure
- [x] `requirements.txt`
- [x] `.gitignore`
- [x] `setup.sh` — virtual environment setup script
- [x] `scripts/seed_db.py` — PokeAPI seeder with `--gen`, `--starters`, `--clean`, `--no-variants` flags
  - Composite `(id, form)` primary key to support regional variants as distinct records
  - Variants (Alolan, Galarian, Hisuian, Paldean) included by default; cosmetic forms excluded
  - Evolution chain resolution discovers variants automatically via species `varieties` endpoint
- [x] `README.md` — setup and seeder documentation
- [x] `ROADMAP.md` — this document

---

### Phase 1 — Data Layer `[complete]`
>
> Branch: `phase/1-data-layer` → merge into `develop`

The foundation everything else depends on. No other phase begins until this is stable and tested.

- [x] `pokedex_rsa/models/pokemon.py`
  - Pokemon dataclass
  - DB connection and access methods
  - CRUD helpers for querying by field values
- [x] `pokedex_rsa/models/resolver.py`
  - Accepts a metadata bundle (dict of field/value pairs)
  - Queries the database for matching Pokemon
  - Returns exactly one match, or raises on zero or multiple matches
- [x] `tests/test_pokemon.py`
- [x] `tests/test_resolver.py`

---

### Phase 2 — Crypto Layer `[complete]`
>
> Branch: `phase/2-crypto` → merge into `develop`

The core of the project. Depends on Phase 1 — uses the resolver to derive primes from Pokemon names.

- [x] `pokedex_rsa/models/crypto.py`
  - SHA-256 name hashing → deterministic prime derivation via Miller-Rabin prime search
  - RSA key generation (`n`, `e=65537`, `d`) from two derived primes
  - Block-based `encrypt(message, public_key)` — arbitrary message length
  - Block-based `decrypt(ciphertext, private_key, public_key)`
- [x] `tests/test_crypto.py`
  - Primality helpers (Miller-Rabin, next_prime)
  - Prime derivation (determinism, uniqueness, bit-range)
  - RSA math (modular inverse, keypair invariants)
  - Round-trip encrypt/decrypt across short, long, unicode, and variant-Pokemon messages

---

### Phase 3 — Controller `[complete]`
>
> Branch: `phase/3-controller` → merge into `develop`

Wires the data and crypto layers into a coherent workflow. Handles error states from the resolver gracefully.

- [x] `pokedex_rsa/controllers/encryption_controller.py`
  - `generate_keypair()` — selects two Pokemon, derives primes, returns keypair + metadata bundles as public key
  - `encrypt(message, public_key_bundle)`
  - `decrypt(ciphertext, private_key, public_key_bundle)`
  - Error handling for ambiguous or unresolvable metadata queries
- [x] `tests/test_encryption_controller.py`
  - Full pipeline end-to-end tests

---

### Phase 4 — CLI `[complete]`
>
> Branch: `phase/4-cli` → merge into `develop`

The user-facing surface. Depends on the controller being stable.

- [x] `pokedex_rsa/views/cli.py`
  - `keygen` — file mode, `--verbose`, and `--fileless` output modes
  - `encrypt` — reads public key from file or inline JSON
  - `decrypt` — reads private key and ciphertext from files or inline JSON
  - `validate` — utility command to test metadata bundles before keygen
- [x] `setup.py` — registers `poke-rsa` CLI entry point
- [x] `requirements.txt` — updated with `click>=8.0.0`
- [x] Smoke tested: fileless pipeline, file pipeline, verbose mode
- [x] Usage section added to README with terminal output examples

---

### Phase 5 — Polish
>
> Branch: `phase/5-polish` → merge into `develop` → merge into `main`

- [ ] CLI test coverage — input validation and error path tests using Click's `CliRunner`
  - Bad JSON on `--bundle-p`, `--bundle-q`, `--public-key`, `--private-key`, `--encrypted`
  - Conflicting flags (`--verbose` + `--fileless`)
  - Missing required flags in `--fileless` mode
  - Nonexistent file paths in file mode
  - Ambiguous and no-match bundles via `keygen` and `validate`
  - Empty message on `encrypt`
- [ ] README cleanup
  - Remove intentional ambiguity from stretch goals (kept as discussion point only)
  - Add Phase 6 UI section as planned next step
- [ ] ROADMAP updated to reflect completed state
- [ ] Any minor consistency or cleanup items identified during CLI testing

---

### Phase 6 — Web UI
>
> Branch: `phase/6-ui` → merge into `develop` → merge into `main`

A minimal web interface for the encryption tool. Lives in `ui/` within the main repo and
imports directly from the `pokedex_rsa` package as a local dependency. The UI does not
replace the CLI — it provides an accessible alternative for demonstration purposes.

#### Interface design

Google Translate-style two-panel layout:

- Left panel: plaintext input
- Right panel: encrypted output (auto-populates on encrypt, or accepts paste for decrypt)
- Key management panel: drag-and-drop or file picker for `private.key` / `public.json`,
  or generate a new keypair inline with metadata bundle inputs and a `validate` helper
- Export buttons: download `encrypted.json` or `plaintext.txt`

#### Planned deliverables

- [ ] `ui/app.py` — Flask application, routes wrapping the encryption controller
- [ ] `ui/templates/index.html` — single-page interface
- [ ] `ui/static/` — CSS and JS
- [ ] `ui/requirements.txt` — Flask and UI-specific dependencies (separate from core)
- [ ] Single-step launch: DB seeding check + Flask server start in one command
  - Either a `poke-rsa-ui` entry point registered in `setup.py`
  - Or a `--serve` flag extension to `setup.sh`
- [ ] README updated with UI setup and usage instructions

---

## Stretch Goals

Ideas to revisit after Phase 6, if the project warrants it.

- **Intentional ambiguity** — allow a sender to craft a public key that matches multiple Pokémon, requiring a shared secret hint to narrow down. Conceptually interesting but better suited to a file-encryption use case than the current message-encryption model. Noted here for completeness.
- **Separate UI repo** — if the web UI grows significantly, splitting `ui/` into its own repo with `pokedex-rsa` as a pip dependency is straightforward. Not necessary while the project is demonstration-focused.
- **P2P messaging** — a minimal peer-to-peer messaging layer using the encryption engine, the originally considered scope for the project.
