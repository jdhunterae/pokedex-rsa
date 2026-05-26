# Pokedex RSA

A proof-of-concept RSA encryption tool that uses Pokémon metadata as the public key exchange mechanism. Instead of sharing a raw numeric key, the sender shares a set of Pokémon attributes (type, height, weight, etc.) that uniquely identify the Pokémon whose name was hashed to derive the prime. The recipient resolves that metadata against a local database to reconstruct the key and decrypt the message.

> ⚠️ **This is a demonstration project.** The prime space is intentionally small (bounded by the ~1025 Pokémon in the national Pokédex) and is not suitable for real-world encryption. The goal is to illustrate RSA concepts and key exchange mechanics in an approachable way.

---

## Setup

```bash
pip install -r requirements.txt
touch data/.gitkeep
```

---

## Database Seeder

The tool runs entirely offline after setup. The seeder script populates a local SQLite database from [PokeAPI](https://pokeapi.co) — run it once before using the encryption tool.

Each Pokémon record stores: name, primary type, secondary type, height (m), weight (kg), base stat total, generation of first appearance, and Pokédex color.

### Commands

**Seed all starter lines (recommended starting point)**

Pulls all three evolution stages for every generation's starters — 81 Pokémon across all nine gens. Good for development and testing since it forces the resolver to work harder at finding unique metadata combinations.

```bash
python scripts/seed_db.py --starters
```

**Seed a specific generation**

```bash
python scripts/seed_db.py --gen 1
```

**Seed multiple generations**

```bash
python scripts/seed_db.py --gen 1 --gen 2
```

**Seed the entire national Pokédex**

Pulls all ~1025 Pokémon. Expect this to take several minutes due to API rate limiting.

```bash
python scripts/seed_db.py
```

### Append behavior

By default the seeder skips any Pokémon already present in the database. This means partial runs are safe to resume, and you can layer generations incrementally:

```bash
python scripts/seed_db.py --gen 1
python scripts/seed_db.py --gen 2   # adds Gen 2 without re-fetching Gen 1
```

### Wiping the database

Use `--clean` to wipe the database before seeding. You will be prompted to confirm.

```bash
python scripts/seed_db.py --clean             # wipe, then pull everything
python scripts/seed_db.py --clean --gen 1     # wipe, then pull Gen 1 only
python scripts/seed_db.py --clean --starters  # wipe, then pull starter lines
```

> `--gen` and `--starters` are mutually exclusive.

---

## Project Structure

```
pokedex-rsa/
├── data/
│   └── pokemon.db          # Local SQLite database (not committed)
├── scripts/
│   └── seed_db.py          # One-time database seeder
├── pokedex_rsa/
│   ├── models/             # Pokemon dataclass, DB access, crypto primitives
│   ├── controllers/        # Orchestrates keygen, encrypt, decrypt
│   └── views/              # CLI interface
├── tests/
├── requirements.txt
└── README.md
```

---

## How It Works

*Full documentation coming as the project develops.*

The core idea:

1. **Key generation** — a Pokémon's name is hashed to derive a large prime *p*. A second Pokémon provides prime *q*. Together they form the RSA modulus *n = p × q*.
2. **Public key exchange** — instead of sharing *p* and *q* directly, the sender shares a metadata bundle (e.g. `{type: grass/poison, height: 2.0, color: green}`) that uniquely identifies each Pokémon in the local database.
3. **Resolution** — the recipient queries their local database with the metadata bundle. If exactly one Pokémon matches, the prime is derived and the message can be decrypted. Ambiguous queries (multiple matches) are rejected.
4. **Encryption / decryption** — standard RSA math on top of the derived primes.

---

## Acknowledgements

Pokémon data provided by [PokeAPI](https://pokeapi.co). Pokémon and all related names are trademarks of Nintendo / Game Freak.
