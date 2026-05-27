# Pokedex RSA

A proof-of-concept RSA encryption tool that uses Pokémon metadata as the public key exchange mechanism. Instead of sharing a raw numeric key, the sender shares a set of Pokémon attributes (type, height, weight, etc.) that uniquely identify the Pokémon whose name was hashed to derive the prime. The recipient resolves that metadata against a local database to reconstruct the key and decrypt the message.

> ⚠️ **This is a demonstration project.** The prime space is intentionally small (bounded by the ~1025 Pokémon in the national Pokédex) and is not suitable for real-world encryption. The goal is to illustrate RSA concepts and key exchange mechanics in an approachable way.

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/your-username/pokedex-rsa.git
cd pokedex-rsa
```

### 2. Run the environment setup script

The setup script handles everything in one step: creates a Python virtual environment if one doesn't exist, activates it in your current shell, and installs all dependencies from `requirements.txt`. It also creates the `data/` directory if it's missing.

```bash
source setup.sh
```

> ⚠️ The script must be run with `source`, not `bash setup.sh`. Using `source` ensures the virtual environment activation persists in your current terminal session. Running it directly as a script would activate the venv inside a subprocess and lose it immediately on exit.

### 3. Seed the local database

The tool runs entirely offline after the initial seed. Run the seeder once to populate the local SQLite database from [PokeAPI](https://pokeapi.co). The starters option is recommended as a starting point:

```bash
python scripts/seed_db.py --starters
```

See the [Database Seeder](#database-seeder) section below for the full list of seeding options.

### Returning to the project later

The setup script is safe to re-run at any time. If the virtual environment already exists it will skip creation and go straight to activation and dependency installation. Just `source` it again at the start of each session:

```bash
source setup.sh
```

Or activate the venv manually if you prefer:

```bash
source .venv/bin/activate
```

---

## Database Seeder

The tool runs entirely offline after setup. The seeder script populates a local SQLite database from [PokeAPI](https://pokeapi.co) — run it once before using the encryption tool.

Each Pokémon record stores: name, form, primary type, secondary type, height (m), weight (kg), base stat total, generation of first appearance, and Pokédex color.

### Regional variants

Regional variants (Alolan, Galarian, Hisuian, Paldean) are stored as distinct records alongside their base forms using a composite `(id, form)` primary key. For example, the Cyndaquil line produces four records rather than three:

```
(155, default)  Cyndaquil        [Fire]
(156, default)  Quilava          [Fire]
(157, default)  Typhlosion       [Fire]
(157, hisui)    Typhlosion-Hisui [Fire / Ghost]
```

This maximises the pool of unique metadata combinations available to the resolver and ensures that variants produce distinct primes from their base forms during key derivation. Cosmetic-only forms (Mega, G-Max, etc.) are excluded as they share types and stats with their base form and would pollute the resolver pool.

### Commands

**Seed all starter lines (recommended starting point)**

Pulls all evolution stages for every generation's starters, including regional variants. Yields approximately 84–90 records across all nine gens — enough to meaningfully stress-test the resolver's uniqueness validation.

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

Pulls all ~1025 species plus regional variants. Expect this to take several minutes due to API rate limiting.

```bash
python scripts/seed_db.py
```

**Skip regional variants**

Any of the above commands can be combined with `--no-variants` to pull base forms only.

```bash
python scripts/seed_db.py --starters --no-variants
python scripts/seed_db.py --gen 1 --no-variants
python scripts/seed_db.py --no-variants
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

### Overview

Pokedex RSA is a demonstration of RSA encryption principles where Pokémon metadata serves as the public key exchange mechanism. The two core ideas are:

1. A Pokémon's name can be deterministically hashed into a large prime number
2. Instead of sharing that prime directly, the sender shares a *metadata puzzle* — a set of attributes that uniquely identifies the Pokémon in the local database

The recipient solves the puzzle, recovers the name, re-derives the prime, and uses it to decrypt the message.

---

### Prime Derivation

The foundation of the system is a deterministic, collision-resistant mapping from Pokémon name to prime number.

**Why not just use the Pokédex number?**
Mapping `#0001 → 2nd prime`, `#0002 → 3rd prime`, etc. produces collisions for regional variants — Kantonian and Hisuian Typhlosion both share Pokédex number 0157, so they would derive the same prime. This breaks the uniqueness guarantee the cryptosystem depends on.

**The solution: SHA-256 name hashing**

Each Pokémon's PokeAPI slug (e.g. `typhlosion`, `typhlosion-hisui`) is UTF-8 encoded and passed through SHA-256, producing a unique 256-bit integer. That integer becomes the starting point for a prime search:

```
hash   = SHA-256("typhlosion-hisui")  →  256-bit integer H
prime  = next_prime(H)                →  first prime ≥ H
```

The forward walk to the next prime uses the Miller-Rabin probabilistic primality test (20 rounds), which provides a false-positive probability of less than 4⁻²⁰ ≈ 10⁻¹² per candidate — sufficient for this application.

**Why this guarantees uniqueness**

SHA-256 is collision-resistant by design: finding two inputs that produce the same hash is computationally infeasible. Two different Pokémon names therefore produce starting points separated by an astronomically large distance on the number line. The average gap between 256-bit primes is approximately 177 numbers (by the prime number theorem), so each name's prime search terminates within a small local neighbourhood that cannot overlap with any other name's neighbourhood.

**Key size**

Derived primes are approximately 256 bits. The RSA modulus `n = p × q` is therefore approximately 512 bits. 512-bit RSA is not considered secure by modern standards — it has been practically factored since 1999. This is an intentional and documented limitation: the prime pool is bounded by the size of the Pokédex, and this project demonstrates RSA principles rather than providing a production cryptosystem. The architecture and mathematics are sound; only the key size falls short of modern security requirements.

---

### Key Generation

Two distinct Pokémon provide the two primes:

```
p = derive_prime("bulbasaur")
q = derive_prime("charmander")
n = p × q                          # RSA modulus (~512 bits)
φ(n) = (p-1)(q-1)                  # Euler's totient
e = 65537                          # public exponent (Fermat prime F₄)
d = e⁻¹ mod φ(n)                   # private exponent (modular inverse)
```

The public exponent `65537` (2¹⁶ + 1) is the standard choice in RSA implementations. It is a Fermat prime, which means it has a short binary representation (exactly two 1-bits), making modular exponentiation fast. It is also large enough to resist small-exponent attacks that affect values like `e=3`.

---

### Public Key Exchange

The sender does not share the prime numbers or the Pokémon names. Instead, they share a **metadata bundle** — a set of Pokémon attributes that uniquely identifies each Pokémon in the local database:

```json
{
  "pokemon_p": { "type_primary": "grass", "type_secondary": "poison", "color": "green" },
  "pokemon_q": { "type_primary": "fire",  "generation": 1,           "height": 0.6    }
}
```

The bundle is valid only if each sub-query resolves to exactly one Pokémon. The sender can use any combination of the stored fields — type, height, weight, base stat total, generation, color, form — and is responsible for choosing a combination that is unambiguous. The tool validates uniqueness before accepting a bundle.

**Non-determinism by design**

The same Pokémon can be described by many different valid metadata bundles. Bulbasaur could be identified by `{type_primary: grass, type_secondary: poison}` one time, or by `{color: green, generation: 1, type_secondary: poison}` another time. This means the public key for the same underlying keypair is never identical across sessions, which is a desirable property.

**Resolution**

The recipient queries their local database with each sub-bundle. The resolver enforces strict uniqueness: zero matches or multiple matches both result in an error. Only an exact single match allows decryption to proceed. Both parties must be using a database seeded from the same source (PokeAPI) for resolution to succeed.

---

### Encryption and Decryption

RSA encrypts integers smaller than the modulus `n`. To handle messages of arbitrary length, the plaintext is split into fixed-size byte blocks sized to fit within `n`, and each block is encrypted independently:

```
block_size = (n.bit_length() // 8) - 1   # safely below n

for each block:
    m = bytes_to_int(block)
    c = m^e mod n                          # encrypt
```

Decryption reverses the process:

```
for each ciphertext integer c:
    m = c^d mod n                          # decrypt
    block = int_to_bytes(m)

plaintext = join(all blocks)
```

Block-based encryption means there is no practical message length limit, and the block size scales automatically as the Pokédex grows and primes become larger in future generations.

---

## Acknowledgements

Pokémon data provided by [PokeAPI](https://pokeapi.co). Pokémon and all related names are trademarks of Nintendo / Game Freak.
