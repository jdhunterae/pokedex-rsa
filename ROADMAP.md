# Pokedex RSA — Project Roadmap

## Branching Strategy

```
main                  # stable, working code only
└── develop           # integration branch, merges into main per phase
    ├── phase/1-data-layer
    ├── phase/2-crypto
    ├── phase/3-controller
    ├── phase/4-cli
    └── phase/5-polish
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

- [ ] Flesh out README with full usage examples and real terminal output
- [ ] Docstrings across all modules
- [ ] Code cleanup and consistency pass
- [ ] Update ROADMAP to reflect completed state
- [ ] Stretch goals (if pursuing):
  - [ ] Intentional ambiguity feature — metadata that resolves to multiple Pokemon, requiring an out-of-band hint

---

## Stretch Goals

Ideas to revisit after Phase 5, if the project warrants it.

- **Intentional ambiguity** — allow a sender to craft a public key that matches multiple Pokemon, requiring a shared secret hint to narrow down. Adds a second layer on top of the metadata resolution.
- **Web UI** — a simple Flask or FastAPI front end wrapping the controller, making the tool more accessible as a demo.
- **P2P messaging** — a minimal peer-to-peer messaging layer using the encryption engine, the originally considered scope for the project.
