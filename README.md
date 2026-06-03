# Pokedex RSA

![Tests](https://github.com/jdhunterae/pokedex-rsa/actions/workflows/tests.yml/badge.svg)

A proof-of-concept RSA encryption tool that uses Pokémon metadata as the public key exchange mechanism. Instead of sharing a raw numeric key, the sender shares a set of Pokémon attributes (type, height, weight, etc.) that uniquely identify the Pokémon whose name was hashed to derive the prime. The recipient resolves that metadata against a local database to reconstruct the key and decrypt the message.

> ⚠️ **This is a demonstration project.** The prime space is intentionally small (bounded by the ~1025 Pokémon in the national Pokédex) and is not suitable for real-world encryption. The goal is to illustrate RSA concepts and key exchange mechanics in an approachable way.

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/jdhunterae/pokedex-rsa.git
cd pokedex-rsa
```

### 2. Run the environment setup script

Creates a Python virtual environment if one doesn't exist, activates it in your current shell, and installs all dependencies. Also creates the `data/` directory if missing.

```bash
source setup.sh
```

> ⚠️ Must be run with `source`, not `bash setup.sh`, so the venv activation persists in your current terminal session.

### 3. Install the package

Registers the `poke-rsa` (CLI) and `poke-rsa-ui` (web UI) entry points:

```bash
pip install -e ".[ui]"
```

### 4. Seed the local database

The tool runs entirely offline after the initial seed. You can seed the database in two ways:

**Option A — Web UI (recommended):** Launch the UI without a database and it will open a setup page automatically:

```bash
poke-rsa-ui
```

**Option B — Command line:**

```bash
python scripts/seed_db.py --starters   # ~84–90 Pokémon, recommended starting point
python scripts/seed_db.py --gen 1      # Gen 1 only
python scripts/seed_db.py              # full national Pokédex (~1025 + variants)
```

See the [Database Seeder](#database-seeder) section for the full list of options.

### Returning to the project later

```bash
source setup.sh        # re-activate venv and install any new dependencies
poke-rsa-ui            # launch the web UI
# or
poke-rsa --help        # use the CLI
```

---

## Launching the Web UI

```bash
poke-rsa-ui
```

Opens at `http://127.0.0.1:5000`. If no database is found, the app redirects to a setup page where you can choose a seeding option and initialise the database without leaving the browser.

**GitHub Codespaces:** the Ports tab in VS Code will show port 5000 with a forwarded URL (`https://<codespace-name>-5000.app.github.dev`) once the server starts.

---

## Database Seeder

Each Pokémon record stores: name, form, primary type, secondary type, height (m), weight (kg), base stat total, generation of first appearance, and Pokédex color.

### Regional variants

Regional variants (Alolan, Galarian, Hisuian, Paldean) are stored as distinct records using a composite `(id, form)` primary key. For example, the Cyndaquil line produces four records:

```
(155, default)  Cyndaquil        [Fire]
(156, default)  Quilava          [Fire]
(157, default)  Typhlosion       [Fire]
(157, hisui)    Typhlosion-Hisui [Fire / Ghost]
```

Cosmetic-only forms (Mega, G-Max, etc.) are excluded as they share types and stats with their base form.

### Commands

```bash
python scripts/seed_db.py --starters          # all starter lines + variants (~84–90 Pokémon)
python scripts/seed_db.py --gen 1             # Gen 1 only
python scripts/seed_db.py --gen 1 --gen 2     # Gen 1 and Gen 2
python scripts/seed_db.py                     # full national Pokédex + variants

# Skip regional variants on any of the above
python scripts/seed_db.py --starters --no-variants

# Wipe and re-seed (prompts for confirmation)
python scripts/seed_db.py --clean --starters
```

By default the seeder skips Pokémon already in the database, so partial runs are safe to resume and you can layer generations incrementally.

> `--gen` and `--starters` are mutually exclusive.

---

## Project Structure

```
pokedex-rsa/
├── data/
│   └── pokemon.db              # Local SQLite database (not committed)
├── scripts/
│   └── seed_db.py              # Database seeder
├── pokedex_rsa/
│   ├── models/                 # Pokemon dataclass, DB access, crypto primitives
│   ├── controllers/            # Orchestrates keygen, encrypt, decrypt, validate
│   └── views/                  # CLI interface
├── ui/
│   ├── app.py                  # Flask application and API routes
│   ├── serve.py                # poke-rsa-ui entry point
│   ├── requirements.txt        # UI-specific dependencies
│   ├── templates/              # index.html, setup.html
│   └── static/
│       ├── css/style.css
│       └── js/                 # app.js, keys.js, setup.js
├── tests/
├── requirements.txt
├── setup.py
└── setup.sh
```

---

## How It Works

### Overview

Pokedex RSA demonstrates RSA encryption where Pokémon metadata serves as the public key exchange mechanism:

1. A Pokémon's name is deterministically hashed into a large prime number
2. Instead of sharing the prime directly, the sender shares a *metadata puzzle* — a set of attributes that uniquely identifies the Pokémon in the local database
3. The recipient resolves the puzzle, recovers the name, re-derives the prime, and decrypts the message

---

### Prime Derivation

Each Pokémon's PokeAPI slug (e.g. `typhlosion`, `typhlosion-hisui`) is UTF-8 encoded and passed through SHA-256, producing a unique 256-bit integer. That integer seeds a forward prime search:

```
hash   = SHA-256("typhlosion-hisui")  →  256-bit integer H
prime  = next_prime(H)                →  first prime ≥ H
```

The prime search uses the Miller-Rabin probabilistic primality test (20 rounds, false-positive probability < 4⁻²⁰ ≈ 10⁻¹²).

**Why not use the Pokédex number?** Regional variants share a Pokédex number — Kantonian and Hisuian Typhlosion are both #0157 — so a number-based mapping would derive the same prime for both. SHA-256 of the name slug is always unique.

**Key size:** Derived primes are ~256 bits, giving a ~512-bit modulus. 512-bit RSA is not secure by modern standards (factored in practice since 1999). This is an intentional limitation — the prime pool is bounded by the Pokédex size.

---

### Key Generation

```
p = derive_prime("bulbasaur")
q = derive_prime("charmander")
n = p × q                          # RSA modulus (~512 bits)
φ(n) = (p-1)(q-1)                  # Euler's totient
e = 65537                          # public exponent (Fermat prime F₄)
d = e⁻¹ mod φ(n)                   # private exponent
```

---

### Public Key Exchange

Instead of sharing `p` and `q`, the sender shares a **metadata bundle** that uniquely identifies each Pokémon:

```json
{
  "bundle_p": { "base_stat_total": 308, "weight": 8.1 },
  "bundle_q": { "type_primary": "fire", "type_secondary": "flying", "generation": 1 }
}
```

The bundle is auto-constructed from the minimum fields needed to uniquely resolve to one Pokémon. The same Pokémon can be described by many different valid bundles, so the public key is never identical across sessions.

---

### Encryption and Decryption

Messages are split into fixed-size byte blocks and each block is encrypted independently:

```
block_size = (n.bit_length() // 8) - 1

for each block:
    m = bytes_to_int(block)
    c = m^e mod n                   # encrypt

for each ciphertext integer c:
    m = c^d mod n                   # decrypt
    block = int_to_bytes(m)
```

Block-based encryption means there is no practical message length limit.

---

## Web UI

The web UI provides a browser-based interface to the full encryption pipeline. Launch it with:

```bash
poke-rsa-ui
```

### Key management

The key panel on the left side of the interface has four states:

| State | Indicator | Description |
|---|---|---|
| Empty | Grey | No keys loaded — generate or upload to begin |
| Partial | Yellow | One of two key files uploaded |
| Mismatch | Yellow | Both files uploaded but keys don't form a valid pair |
| Valid | Green | Both keys loaded, validated, and ready |

**Generating a keypair**

Use the filter dropdowns and search box to narrow the Pokémon pool for each slot (P and Q). All eight metadata fields are available as filters:

| Field | Type |
|---|---|
| Primary type | Dropdown |
| Secondary type | Dropdown (`none` for single-type) |
| Generation | Dropdown (1–9) |
| Color | Dropdown |
| Form | Dropdown (default, alola, galar, hisui, paldea) |
| BST | Integer |
| Height (m) | Decimal |
| Weight (kg) | Decimal |

The live counter next to each filter slot (`8 / 1078`) shows how many Pokémon match the current filters. Type in the search box to find a specific Pokémon by name — clicking a result locks that slot to that Pokémon exactly. The Generate Keypair button is disabled if either pool is empty or if identical filters produce a pool of fewer than 2.

After generating, the key info card shows which Pokémon were selected and the modulus size. Use the `↓ private.key` and `↓ public.json` buttons to download and preserve your keys for future sessions.

**Uploading existing keys**

Drag a file onto the `private.key` or `public.json` slot, or click a slot to browse. The app detects misrouted files (e.g. uploading `public.json` to the private key slot) and surfaces a specific error. When both slots are filled, the app automatically validates the pair and confirms they work together before enabling the encryption panels.

**Purging keys**

The Purge Session Keys button clears both key files from the session. The generate and upload sections reappear. Individual slot clearing is intentionally not supported — if keys don't match, purge both and start over.

---

### Encrypting and decrypting

The two-panel layout works like a translate interface:

- Type or paste plaintext in the left panel → ciphertext appears on the right after 800ms
- Paste or drop an `encrypted.json` file into the right panel → plaintext appears on the left

Both panels accept drag-and-drop (`.txt` for plaintext, `.json` for ciphertext) as well as click-to-import via the **Import** button in each panel header. The **Export** buttons download the current panel content as a file.

If you try to decrypt a message that was encrypted with different keys, the app detects the mismatch before attempting decryption and surfaces a clear error rather than a cryptic server exception.

---

### Database management

The **Reset DB** button in the top-right header deletes the local database after confirmation and redirects to the setup page to re-seed. Use this when switching between full and starter-only databases, or to reset to a clean state.

---

## CLI Usage

### Commands

#### `count` — check pool size before generating

```bash
poke-rsa count
# 1025 Pokemon in the database.

poke-rsa count --bundle '{"type_primary":"fire"}'
# 64 Pokemon match {"type_primary": "fire"} (out of 1025 total)
```

#### `validate` — confirm a bundle resolves to exactly one Pokémon

```bash
poke-rsa validate --bundle '{"type_primary":"grass","base_stat_total":308}'
# ✓ Bundle resolves to: #0495 Snivy (grass, Gen 5, 0.6m, 8.1kg, BST 308)
```

#### `keygen` — generate a keypair

All filter flags are optional and can be combined freely. `--bundle-p/q` takes precedence over individual filter flags when both are provided.

**Modes (applied independently to P and Q):**

| Mode | Description |
|---|---|
| No flags | Fully random from entire database |
| Filter flags | Random from matching pool |
| `--bundle-p/q` | Exact JSON bundle |

**Individual filter flags:**

| Flag | Type | Description |
|---|---|---|
| `--type-primary-p/q` | text | Primary type (e.g. `fire`, `water`) |
| `--type-secondary-p/q` | text | Secondary type; use `none` for single-type |
| `--generation-p/q` | integer | Generation (1–9) |
| `--color-p/q` | text | Pokédex color |
| `--form-p/q` | text | Form (`default`, `alola`, `galar`, `hisui`, `paldea`) |
| `--bst-p/q` | integer | Base stat total |
| `--height-p/q` | float | Height in metres |
| `--weight-p/q` | float | Weight in kg |

```bash
poke-rsa keygen                                      # fully random
poke-rsa keygen --fileless                           # fully random, terminal output
poke-rsa keygen --type-primary-p fire --generation-p 1
poke-rsa keygen --bundle-p '{"type_primary":"grass","base_stat_total":308}'
poke-rsa keygen --type-primary-p water --type-primary-q fire --fileless
```

#### `encrypt` — encrypt a message

```bash
poke-rsa encrypt --message "Hello, Trainer!"
# reads public.json, writes encrypted.json

poke-rsa encrypt --fileless --message "Hello!" --public-key '<paste public bundle>'
```

#### `decrypt` — decrypt a message

The CLI performs a pre-flight key validation before attempting decryption, surfacing a clear error if the message was encrypted with different keys.

```bash
poke-rsa decrypt
# reads private.key + encrypted.json, writes plaintext.txt

poke-rsa decrypt --fileless --private-key '<paste>' --encrypted '<paste>'
```

#### Output modes

| Flag | Files written | Terminal output |
|---|---|---|
| *(default)* | ✓ | Brief confirmation only |
| `--verbose` | ✓ | Full key / message content |
| `--fileless` | ✗ | Full key / message content |

> `--verbose` and `--fileless` are mutually exclusive.

---

## Acknowledgements

Pokémon data provided by [PokeAPI](https://pokeapi.co). Pokémon and all related names are trademarks of Nintendo / Game Freak.