# Contributing to Pokedex RSA

Thank you for your interest in contributing. This document covers setup,
branching conventions, and the requirements for submitting changes.

---

## Getting started

### Prerequisites

- Python 3.12 or higher
- Git

### Setup

```bash
git clone https://github.com/jdhunterae/pokedex-rsa.git
cd pokedex-rsa
source setup.sh          # creates venv, installs dependencies
pip install -e ".[ui]"   # registers poke-rsa and poke-rsa-ui entry points
python scripts/seed_db.py --starters   # seed a development database
```

---

## Branching conventions

The project uses a phase-based branching strategy:

```
main        stable, release-ready code only
develop     integration branch; merges into main per phase
phase/*     feature branches; cut from develop, merge back into develop
```

For a contribution:

1. Cut your branch from `develop`:

   ```bash
   git checkout develop
   git checkout -b phase/your-feature-name
   ```

2. Make your changes, commit with descriptive messages
3. Open a pull request targeting `develop`

---

## Running tests

All changes must pass the full test suite before merging:

```bash
python -m pytest tests/ -v
```

The project uses GitHub Actions to run tests automatically on every push and
pull request to `main` and `develop`. The badge in the README reflects the
current status of the `main` branch.

### Test structure

| File | What it covers |
|---|---|
| `tests/test_pokemon.py` | Pokemon dataclass and DB access layer |
| `tests/test_resolver.py` | Metadata resolver and uniqueness validation |
| `tests/test_crypto.py` | Prime derivation, RSA math, encrypt/decrypt |
| `tests/test_encryption_controller.py` | Full pipeline, keygen modes, serialisation |
| `tests/test_cli.py` | CLI input validation and error paths |

All tests use in-memory SQLite fixtures and do not require a seeded database.

### Adding tests

New functionality should include tests. New CLI commands or flags belong in
`test_cli.py`. New controller methods belong in `test_encryption_controller.py`.
Use the existing in-memory fixture pattern — do not depend on the real
`data/pokemon.db`.

---

## Code style

- **Python:** follow PEP 8; docstrings on all public functions and classes
- **JavaScript:** consistent with the existing `ui/static/js/` style —
  plain ES2020, no bundler, no frameworks beyond what's already in use
- **CSS:** add new rules in the relevant section of `style.css` with a
  `/* ── section name */` comment header

---

## Project structure

```
pokedex_rsa/
  models/       Pokemon dataclass, DB access, RSA primitives
  controllers/  Encryption pipeline orchestration
  views/        CLI (Click)
ui/
  app.py        Flask API routes
  serve.py      poke-rsa-ui entry point
  templates/    Jinja2 HTML templates
  static/       CSS and JavaScript
scripts/
  seed_db.py    PokeAPI database seeder
tests/          pytest test suite
```

---

## Security note

This project is a **demonstration tool** and is not suitable for protecting
real sensitive data. The RSA key size (~512 bits) is intentionally limited by
the Pokédex pool size. Do not use this for actual encryption needs.
