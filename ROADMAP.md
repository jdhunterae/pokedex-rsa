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
    ├── phase/6-ui
    └── phase/7-ui-polish
```

Each phase branch cuts from `develop`, gets merged back into `develop` when complete.
`develop` merges into `main` at the end of each phase once verified stable.
`main` always represents a working, if incomplete, state of the project.

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
- [x] `README.md` — setup and seeder documentation
- [x] `ROADMAP.md` — this document

---

### Phase 1 — Data Layer `[complete]`
>
> Branch: `phase/1-data-layer` → merge into `develop`

- [x] `pokedex_rsa/models/pokemon.py` — Pokemon dataclass, DB access, `find_by()`
- [x] `pokedex_rsa/models/resolver.py` — metadata query → unique Pokemon or raise
- [x] `tests/test_pokemon.py`
- [x] `tests/test_resolver.py`

---

### Phase 2 — Crypto Layer `[complete]`
>
> Branch: `phase/2-crypto` → merge into `develop`

- [x] `pokedex_rsa/models/crypto.py` — SHA-256 prime derivation, RSA keygen, block encrypt/decrypt
- [x] `tests/test_crypto.py`

---

### Phase 3 — Controller `[complete]`
>
> Branch: `phase/3-controller` → merge into `develop`

- [x] `pokedex_rsa/controllers/encryption_controller.py` — keygen, encrypt, decrypt, validate
- [x] `tests/test_encryption_controller.py`

---

### Phase 4 — CLI `[complete]`
>
> Branch: `phase/4-cli` → merge into `develop`

- [x] `pokedex_rsa/views/cli.py` — `keygen`, `encrypt`, `decrypt`, `validate`, `count` commands
- [x] `setup.py` — registers `poke-rsa` and `poke-rsa-ui` entry points
- [x] Smoke tested across all output modes

---

### Phase 5 — Polish `[complete]`
>
> Branch: `phase/5-polish` → merge into `develop` → merge into `main`

- [x] `tests/test_cli.py` — 45 CLI input validation and error path tests
- [x] README usage section with verified terminal output examples
- [x] `.gitignore` updated with CLI output files

---

### Phase 5.5 — Core Updates `[complete]`
>
> Branch: `phase/5.5-core-updates` → merge into `develop`

- [x] Random / restricted keygen — `generate_keypair()` accepts optional partial bundles
- [x] `_build_minimal_bundle()` — auto-constructs tightest unique public bundle
- [x] `count_candidates()` — exposes pool size for UI filter counter
- [x] `list_candidates()` — returns Pokemon objects for autocomplete
- [x] `validate_keypair()` — checks n = p×q against private key n
- [x] CLI `keygen` bundles made optional; `count` command added
- [x] 221 tests passing

---

### Phase 6 — Web UI `[complete]`
>
> Branch: `phase/6-ui` → merge into `develop` → merge into `main`

- [x] `ui/app.py` — Flask application with full API route set
- [x] `ui/templates/index.html` — main single-page UI
- [x] `ui/templates/setup.html` — DB initialization screen with progress polling
- [x] `ui/static/css/style.css` — retro terminal × Pokédex aesthetic
- [x] `ui/static/js/app.js` — live encrypt/decrypt with 800ms debounce
- [x] `ui/static/js/keys.js` — key management state machine
- [x] `ui/static/js/setup.js` — DB seeder with polling progress
- [x] `ui/serve.py` — `poke-rsa-ui` entry point with DB check on launch
- [x] `ui/requirements.txt`

---

### Phase 7 — UI Polish & Convenience Features
>
> Branch: `phase/7-ui-polish` → merge into `develop` → merge into `main`

#### Key panel UX

- [x] **Purge button positioning** — moved directly below key status / key info
- [x] **Hide generate and upload when keys are loaded** — sections collapse when
      a keypair is active; user must purge before generating or uploading new keys
- [x] **Full key management state machine** — four states: empty, partial,
      mismatch, unresolvable, valid; each with appropriate indicator, message,
      and available actions
- [x] **Smart upload validation** — misrouted files detected by structure
      (public.json in private slot and vice versa) with clear redirect message;
      corrupt/unrecognised files produce specific errors. Redirect offer not
      implemented — warning is sufficient given the all-or-nothing purge model.
- [x] **Key export / download** — `↓ private.key` and `↓ public.json` buttons
      appear in the loaded state; served via `GET /api/session/download/*`
- [x] **Full filter UI for keygen** — dynamic filter rows supporting all 8
      metadata fields; search-with-autocomplete for direct Pokémon selection;
      lock state disables filters once a Pokémon is chosen; generate button
      guard prevents impossible pool combinations

#### File drag-and-drop on text panels

- [ ] **Drag-and-drop `encrypted.json` onto the ciphertext panel**
- [ ] **Drag-and-drop `.txt` onto the plaintext panel**

#### Database management

- [ ] **Reset database from UI** — settings link in header → confirmation dialog
      → `DELETE /api/setup/database` → redirect to `/setup`

#### Decryption error messaging

- [ ] **Key mismatch on decrypt** — pre-flight check in `/api/decrypt` that
      resolves the message's embedded public bundle Pokemon and compares against
      the session's current keys before attempting decryption; surfaces
      *"This message was encrypted with different keys"* rather than a raw
      Python exception

---

## Stretch Goals

- **Intentional ambiguity** — public key that matches multiple Pokémon,
  requiring a shared secret hint. Better suited to file encryption than the
  current message model.
- **Separate UI repo** — split `ui/` into its own repo with `pokedex-rsa`
  as a pip dependency if the UI grows significantly.
- **P2P messaging** — peer-to-peer layer using the encryption engine; requires
  a user profile system where each user's public bundle is shareable on request.
