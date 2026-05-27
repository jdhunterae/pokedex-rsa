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
    ├── phase/5.5-core-updates
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

- [x] `pokedex_rsa/models/crypto.py`
  - SHA-256 name hashing → deterministic prime derivation via Miller-Rabin prime search
  - RSA key generation (`n`, `e=65537`, `d`) from two derived primes
  - Block-based `encrypt(message, public_key)` — arbitrary message length
  - Block-based `decrypt(ciphertext, private_key, public_key)`
- [x] `tests/test_crypto.py`

---

### Phase 3 — Controller `[complete]`
>
> Branch: `phase/3-controller` → merge into `develop`

- [x] `pokedex_rsa/controllers/encryption_controller.py`
  - `generate_keypair()` — two resolved bundles → keypair + metadata public key
  - `encrypt(message, public_key_bundle)`
  - `decrypt(ciphertext, private_key, public_key_bundle)`
  - Error handling for ambiguous or unresolvable metadata queries
- [x] `tests/test_encryption_controller.py`

---

### Phase 4 — CLI `[complete]`
>
> Branch: `phase/4-cli` → merge into `develop`

- [x] `pokedex_rsa/views/cli.py`
  - `keygen`, `encrypt`, `decrypt`, `validate` commands
  - File mode, `--verbose`, and `--fileless` output modes
- [x] `setup.py` — registers `poke-rsa` CLI entry point
- [x] `requirements.txt` — updated with `click>=8.0.0`
- [x] Smoke tested across all output modes

---

### Phase 5 — Polish `[complete]`
>
> Branch: `phase/5-polish` → merge into `develop` → merge into `main`

- [x] `tests/test_cli.py` — 45 CLI input validation and error path tests
  - Found and fixed real bug: invalid field names in `validate` raised unhandled `ValueError`
- [x] README usage section with verified terminal output examples
- [x] `.gitignore` updated with CLI output files
- [x] ROADMAP updated to reflect completed state

---

### Phase 5.5 — Core Updates
>
> Branch: `phase/5.5-core-updates` → merge into `develop`

Prepares the core library and CLI for the web UI. The UI requires random and
restricted key generation — the current controller only supports fully resolved
bundles. This phase updates the controller, adds auto-bundle construction, and
makes CLI bundle flags optional before any UI work begins.

#### Controller updates (`encryption_controller.py`)

- [ ] Random keygen — `generate_keypair()` accepts optional partial bundles
  - No bundle provided → pick randomly from entire DB
  - Partial bundle provided → pick randomly from matching pool
  - Exact unique bundle provided → existing behavior (resolve to one Pokemon)
- [ ] `_build_minimal_bundle(pokemon)` — auto-construct the tightest unique
      metadata bundle for a randomly selected Pokemon
  - Tries field combinations in order of distinctiveness until one resolves uniquely
  - Used to produce the shareable public key when the user did not specify a bundle
- [ ] `count_candidates(partial_bundle)` — return the number of Pokemon matching
      a partial bundle without resolving to a unique one
  - Exposes `len(resolver.candidates(bundle))` cleanly for the UI counter
- [ ] `random_pokemon(partial_bundle)` — select one Pokemon at random from the
      matching pool, used internally by random keygen

#### CLI updates (`cli.py`)

- [ ] `--bundle-p` / `--bundle-q` become optional on `keygen`
  - Omitted → fully random selection
  - Partial bundle (multiple matches) → restricted random selection
  - Exact bundle (one match) → existing exact behavior
- [ ] `keygen` output always shows which Pokemon were selected, regardless of
      whether the user specified bundles or let the tool choose
- [ ] Update `--help` text to reflect optional bundle flags
- [ ] Add `count` command — accepts a partial bundle, returns match count

  ```bash
  poke-rsa count --bundle '{"type_primary":"grass"}'
  # 174 Pokemon match this bundle (out of 1025 total)
  ```

#### Test updates

- [ ] `tests/test_encryption_controller.py` — new tests for random keygen paths
  - Random with no bundle produces valid keypair
  - Restricted random with partial bundle picks from correct pool
  - Auto-bundle always produces a uniquely resolvable result
  - `count_candidates` returns correct counts
- [ ] `tests/test_cli.py` — update tests that assume `--bundle-p/q` are required
  - `keygen` with no bundles succeeds
  - `keygen` with partial bundles (multiple matches) succeeds
  - `count` command happy path and error paths

---

### Phase 6 — Web UI
>
> Branch: `phase/6-ui` → merge into `develop` → merge into `main`

A minimal single-page web interface living in `ui/` within the main repo.
Imports directly from `pokedex_rsa` as a local dependency. Does not replace
the CLI — provides an accessible alternative for demonstration purposes.

#### Session model

- Private and public key files stored in a temp directory scoped to the session ID
- User never sees raw key content — keys are loaded/generated and quietly held
- User can replace or purge session keys at any time

#### Interface — main page (`/`)

Google Translate-style two-panel layout:

- **Left panel** — plaintext input
- **Right panel** — encrypted output (paste encrypted text here to decrypt)
- Direction is determined by which panel was last edited
- Live update with 800ms debounce after last keystroke — no explicit button
- Both panels disabled and show prompt if no keys are loaded

#### Interface — key management panel

- Drag-and-drop or file picker for uploading existing `private.key` / `public.json`
- Generate new keypair inline:
  - Optional filter fields via dropdowns (type, generation, color, form)
  - Live counter showing how many Pokemon match current filters
    (e.g. "174 Pokemon match · out of 1025 total")
  - Generates randomly from matching pool — user sees which Pokemon were chosen
  - Auto-uploads generated keys to session immediately
- Purge / replace keys button

#### Interface — setup page (`/setup`)

Shown instead of main UI when `data/pokemon.db` is missing or empty:

- Seeding options: starters only, specific generations, or full dex
- Progress feedback while seeder runs
- Redirects to main UI on completion

#### Planned deliverables

- [ ] `ui/app.py` — Flask application and API routes
- [ ] `ui/templates/index.html` — main single-page UI
- [ ] `ui/templates/setup.html` — DB initialization screen
- [ ] `ui/static/css/style.css`
- [ ] `ui/static/js/app.js` — main UI logic and live update listeners
- [ ] `ui/static/js/keys.js` — key management panel
- [ ] `ui/static/js/setup.js` — DB initialization page
- [ ] `ui/requirements.txt` — Flask and UI-specific dependencies
- [ ] Single-step launch — `poke-rsa-ui` entry point or `--serve` flag on `setup.sh`
  - Checks DB on startup, redirects to `/setup` if empty
  - Seeds check before serving first request
- [ ] README updated with UI setup and usage instructions

#### API routes

```
GET  /                      → main UI (or redirect to /setup if DB empty)
GET  /setup                 → DB initialization page
POST /api/setup/seed        → trigger seeder with options, return job ID
GET  /api/setup/status      → poll seeder progress

POST /api/session/keys      → upload key files, store in temp dir
POST /api/session/keygen    → random or restricted keygen, auto-store in temp dir
DELETE /api/session/keys    → purge session keys and temp dir

POST /api/bundle/count      → count matching Pokemon for a partial bundle
POST /api/bundle/validate   → validate a bundle resolves to exactly one Pokemon

POST /api/encrypt           → encrypt with session public key
POST /api/decrypt           → decrypt with session private key
```

---

## Stretch Goals

Ideas to revisit after Phase 6, if the project warrants it.

- **Intentional ambiguity** — allow a sender to craft a public key that matches
  multiple Pokémon, requiring a shared secret hint to narrow down. Better suited
  to a file-encryption use case than the current message-encryption model.
- **Separate UI repo** — if the web UI grows significantly, splitting `ui/` into
  its own repo with `pokedex-rsa` as a pip dependency is straightforward.
- **P2P messaging** — a minimal peer-to-peer messaging layer using the encryption
  engine. Would require a user profile system where each user's public bundle is
  shareable on request — the natural evolution of the current key exchange model.
