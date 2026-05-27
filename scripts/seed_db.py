#!/usr/bin/env python3
"""
seed_db.py - Populate the local Pokemon SQLite database from PokeAPI.

Usage:
    python seed_db.py                           # Append all Pokemon + variants, skip existing
    python seed_db.py --gen 1                   # Append Gen 1 only (+ variants)
    python seed_db.py --gen 1 --gen 2           # Append Gen 1 and Gen 2
    python seed_db.py --starters                # Append all starter lines + Hisui variants
    python seed_db.py --clean                   # Wipe DB, then pull everything
    python seed_db.py --clean --gen 1           # Wipe DB, then pull Gen 1 only
    python seed_db.py --clean --starters        # Wipe DB, then pull starter lines
    python seed_db.py --no-variants             # Skip alternate forms (base forms only)
"""

import argparse
import sqlite3
import time
import sys
import os
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "pokemon.db")
POKEAPI_BASE = "https://pokeapi.co/api/v2"
REQUEST_DELAY = 0.5  # seconds between API calls to respect rate limits

# Base starter Pokedex IDs (first stage only), one row per gen.
# Evolution chains are resolved dynamically so adding a future gen
# only requires appending three IDs here.
STARTER_BASE_IDS = [
    1,   4,   7,    # Gen 1: Bulbasaur, Charmander, Squirtle
    152, 155, 158,  # Gen 2: Chikorita, Cyndaquil, Totodile
    252, 255, 258,  # Gen 3: Treecko, Torchic, Mudkip
    387, 390, 393,  # Gen 4: Turtwig, Chimchar, Piplup
    495, 498, 501,  # Gen 5: Snivy, Tepig, Oshawott
    650, 653, 656,  # Gen 6: Chespin, Fennekin, Froakie
    722, 725, 728,  # Gen 7: Rowlet, Litten, Popplio
    810, 813, 816,  # Gen 8: Grookey, Scorbunny, Sobble
    906, 909, 912,  # Gen 9: Sprigatito, Fuecoco, Quaxly
]

# Pokedex ID ranges per generation (national dex)
GEN_RANGES = {
    1: (1,   151),
    2: (152, 251),
    3: (252, 386),
    4: (387, 493),
    5: (494, 649),
    6: (650, 721),
    7: (722, 809),
    8: (810, 905),
    9: (906, 1025),
}

# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------


def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db(conn):
    """
    Schema uses (id, form) as a composite primary key so regional variants
    of the same species are stored as distinct rows.

    form defaults to 'default' for the standard form of each Pokemon.
    Variants use the slug suffix from PokeAPI (e.g. 'hisui', 'alola', 'galar').
    The name field holds the full PokeAPI slug (e.g. 'typhlosion-hisui') and
    is the value hashed during prime derivation, ensuring variants produce
    distinct primes from their base forms.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pokemon (
            id              INTEGER NOT NULL,
            form            TEXT    NOT NULL DEFAULT 'default',
            name            TEXT    NOT NULL UNIQUE,
            type_primary    TEXT    NOT NULL,
            type_secondary  TEXT,
            height          REAL    NOT NULL,
            weight          REAL    NOT NULL,
            base_stat_total INTEGER NOT NULL,
            generation      INTEGER NOT NULL,
            color           TEXT    NOT NULL,
            PRIMARY KEY (id, form)
        )
    """)
    conn.commit()


def clean_db(conn):
    conn.execute("DROP TABLE IF EXISTS pokemon")
    conn.commit()
    print("Database wiped.")

# ---------------------------------------------------------------------------
# PokeAPI helpers
# ---------------------------------------------------------------------------


def fetch(url):
    """GET a URL and return parsed JSON, with basic retry on failure."""
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            if attempt == 2:
                raise
            print(f"  Retrying ({attempt + 1}/3) after error: {e}")
            time.sleep(2)


def get_generation_number(gen_url):
    """Extract the integer generation number from a generation resource URL."""
    data = fetch(gen_url)
    roman = data["name"].split("-")[1].upper()
    roman_map = {
        "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5,
        "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10
    }
    return roman_map.get(roman, 0)


def extract_form_slug(pokemon_name, species_name):
    """
    Derive a clean form slug from the full PokeAPI pokemon name.

    Examples:
        'typhlosion'        + 'typhlosion' -> 'default'
        'typhlosion-hisui'  + 'typhlosion' -> 'hisui'
        'meowth-alola'      + 'meowth'     -> 'alola'
        'mr-mime-galar'     + 'mr-mime'    -> 'galar'
    """
    if pokemon_name == species_name:
        return "default"
    prefix = species_name + "-"
    if pokemon_name.startswith(prefix):
        return pokemon_name[len(prefix):]
    return pokemon_name  # fallback: use full name as form slug


def fetch_pokemon_record(pokemon_slug, species_data):
    """
    Pull all required fields for a single Pokemon form by its PokeAPI slug.
    species_data is passed in to avoid redundant API calls when fetching
    multiple forms of the same species.

    Returns a dict ready for DB insertion, or None on failure.
    """
    try:
        poke_data = fetch(f"{POKEAPI_BASE}/pokemon/{pokemon_slug}")
        time.sleep(REQUEST_DELAY)

        species_name = species_data["name"]
        name = poke_data["name"]
        form = extract_form_slug(name, species_name)

        types = [t["type"]["name"] for t in poke_data["types"]]
        type_primary = types[0] if len(types) > 0 else None
        type_secondary = types[1] if len(types) > 1 else None

        # PokeAPI stores height in decimetres, weight in hectograms
        height = poke_data["height"] / 10.0  # -> metres
        weight = poke_data["weight"] / 10.0  # -> kg

        base_stat_total = sum(s["base_stat"] for s in poke_data["stats"])
        generation = get_generation_number(species_data["generation"]["url"])
        time.sleep(REQUEST_DELAY)

        color = species_data["color"]["name"]

        return {
            "id":             species_data["id"],
            "form":           form,
            "name":           name,
            "type_primary":   type_primary,
            "type_secondary": type_secondary,
            "height":         height,
            "weight":         weight,
            "base_stat_total": base_stat_total,
            "generation":     generation,
            "color":          color,
        }

    except Exception as e:
        print(f"  ERROR fetching '{pokemon_slug}': {e}")
        return None


def fetch_all_forms(species_id, include_variants=True):
    """
    Given a species Pokedex ID, return a list of dicts ready for DB insertion —
    one for the default form plus one per regional variant (if include_variants).

    Variants are identified via the species.varieties field. Each variety object
    contains a "pokemon" key (not "variety") with the form's name and URL.
    Any variety where is_default=False and whose name contains a known region
    suffix is included.
    Cosmetic-only forms (mega, gmax, totem, etc.) are excluded since they share
    stats/types with the base form and would pollute the resolver pool.
    """
    EXCLUDED_SUFFIXES = {
        "mega", "mega-x", "mega-y", "gmax", "totem",
        "primal", "eternamax", "starter", "partner",
        "original", "zen", "school", "busted", "disguised",
        "blade", "dawn", "dusk", "midday", "midnight",
        "pirouette", "red-striped", "blue-striped",
        "small", "average", "large", "super",
        "sandy", "trash", "plant",
        "sunshine", "rainy", "snowy",
    }

    REGIONAL_SUFFIXES = {"alola", "galar", "hisui", "paldea"}

    try:
        species_data = fetch(f"{POKEAPI_BASE}/pokemon-species/{species_id}")
        time.sleep(REQUEST_DELAY)

        varieties = species_data.get("varieties", [])
        records = []

        for variety in varieties:
            slug = variety["pokemon"]["name"]
            is_default = variety["is_default"]

            if not is_default:
                # Extract the suffix after the species name
                suffix = extract_form_slug(slug, species_data["name"])

                # Skip cosmetic/battle forms
                if suffix in EXCLUDED_SUFFIXES:
                    continue

                # Only include if it's a recognised regional variant
                if not include_variants or suffix not in REGIONAL_SUFFIXES:
                    continue

            record = fetch_pokemon_record(slug, species_data)
            if record:
                records.append(record)

        return records

    except Exception as e:
        print(f"  ERROR fetching forms for species #{species_id}: {e}")
        return []

# ---------------------------------------------------------------------------
# DB insertion
# ---------------------------------------------------------------------------


def record_exists(conn, pokemon_id, form):
    return conn.execute(
        "SELECT 1 FROM pokemon WHERE id = ? AND form = ?", (pokemon_id, form)
    ).fetchone() is not None


def insert_record(conn, record, skip_existing=True):
    """Insert a Pokemon record. Returns 'inserted', 'skipped', or 'error'."""
    if skip_existing and record_exists(conn, record["id"], record["form"]):
        return "skipped"

    try:
        conn.execute("""
            INSERT OR REPLACE INTO pokemon
                (id, form, name, type_primary, type_secondary, height, weight,
                 base_stat_total, generation, color)
            VALUES
                (:id, :form, :name, :type_primary, :type_secondary, :height,
                 :weight, :base_stat_total, :generation, :color)
        """, record)
        conn.commit()
        return "inserted"
    except sqlite3.Error as e:
        print(f"  DB error for #{record['id']} ({record['form']}): {e}")
        return "error"

# ---------------------------------------------------------------------------
# Evolution chain resolution
# ---------------------------------------------------------------------------


def get_evolution_chain_species_ids(base_species_id):
    """
    Given a base-stage species ID, return all species IDs in its evolution
    chain in order (base -> middle -> final). Returns a list of 1-3 IDs.
    """
    try:
        species_data = fetch(
            f"{POKEAPI_BASE}/pokemon-species/{base_species_id}")
        time.sleep(REQUEST_DELAY)

        chain_data = fetch(species_data["evolution_chain"]["url"])
        time.sleep(REQUEST_DELAY)

        ids = []
        node = chain_data["chain"]
        while node:
            sp = fetch(
                f"{POKEAPI_BASE}/pokemon-species/{node['species']['name']}")
            time.sleep(REQUEST_DELAY)
            ids.append(sp["id"])
            node = node["evolves_to"][0] if node["evolves_to"] else None

        return ids

    except Exception as e:
        print(f"  ERROR resolving evolution chain for #{base_species_id}: {e}")
        return [base_species_id]

# ---------------------------------------------------------------------------
# Main seed routine
# ---------------------------------------------------------------------------


def seed(species_ids, skip_existing=True, include_variants=True):
    conn = get_connection()
    init_db(conn)

    total = len(species_ids)
    inserted = skipped = errors = 0

    variant_label = "including regional variants" if include_variants else "base forms only"
    mode_label = "append (skip existing)" if skip_existing else "overwrite"
    print(f"\nFetching {total} species ({variant_label})...")
    print(f"Mode: {mode_label}\n")

    for i, species_id in enumerate(species_ids, 1):
        print(f"[{i}/{total}] species #{species_id}", end=" ", flush=True)

        # Fast-path: if the default form already exists and we're skipping, check
        # before hitting the API at all.
        if skip_existing and record_exists(conn, species_id, "default"):
            print(f"→ skipped (already in DB)")
            skipped += 1
            continue

        records = fetch_all_forms(
            species_id, include_variants=include_variants)
        if not records:
            print(f"→ no records returned")
            errors += 1
            continue

        for record in records:
            result = insert_record(conn, record, skip_existing=skip_existing)
            form_label = f" [{record['form']}]" if record["form"] != "default" else ""
            if result == "inserted":
                print(
                    f"\n  ✓ {record['name']}{form_label} "
                    f"(Gen {record['generation']}, "
                    f"{record['type_primary']}"
                    f"{'/' + record['type_secondary'] if record['type_secondary'] else ''}, "
                    f"BST {record['base_stat_total']})"
                )
                inserted += 1
            elif result == "skipped":
                print(f"\n  – {record['name']}{form_label} skipped")
                skipped += 1
            else:
                errors += 1

        print()  # newline after each species block

    conn.close()

    print(f"{'='*50}")
    print(
        f"Done. Inserted: {inserted} | Skipped: {skipped} | Errors: {errors}")
    print(f"Database: {os.path.abspath(DB_PATH)}")


def seed_starters(skip_existing=True, include_variants=True):
    print("Resolving evolution chains for all starters...")
    all_species_ids = []

    for base_id in STARTER_BASE_IDS:
        print(f"  Resolving chain for #{base_id}...", end=" ", flush=True)
        chain_ids = get_evolution_chain_species_ids(base_id)
        print(f"-> {chain_ids}")
        all_species_ids.extend(chain_ids)

    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for sid in all_species_ids:
        if sid not in seen:
            seen.add(sid)
            deduped.append(sid)

    variant_note = " + regional variants" if include_variants else " (base forms only)"
    print(
        f"\nResolved {len(deduped)} unique species across all starter lines{variant_note}.\n")
    seed(deduped, skip_existing=skip_existing,
         include_variants=include_variants)


def ids_for_gens(gens):
    ids = []
    for gen in gens:
        if gen not in GEN_RANGES:
            print(f"Warning: unknown generation {gen}, skipping.")
            continue
        start, end = GEN_RANGES[gen]
        ids.extend(range(start, end + 1))
    return ids

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Seed the local Pokemon database from PokeAPI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "--gen", type=int, action="append", metavar="N",
        help="Pull only this generation (1-9). Repeatable for multiple gens."
    )
    parser.add_argument(
        "--starters", action="store_true",
        help="Pull all evolution stages for every gen's starters, including regional variants."
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="Wipe the existing database before pulling. Cannot be undone."
    )
    parser.add_argument(
        "--no-variants", action="store_true",
        help="Skip regional variants (Alolan, Galarian, Hisuian, Paldean). Pull base forms only."
    )

    args = parser.parse_args()

    # Validate
    if args.gen and args.starters:
        print("Error: --gen and --starters are mutually exclusive.")
        sys.exit(1)

    if args.gen:
        for g in args.gen:
            if g not in GEN_RANGES:
                print(f"Error: --gen must be between 1 and 9 (got {g}).")
                sys.exit(1)

    # Confirm clean
    if args.clean:
        confirm = input(
            "--clean will permanently wipe the database. Continue? [y/N] ")
        if confirm.strip().lower() != "y":
            print("Aborted.")
            sys.exit(0)
        conn = get_connection()
        clean_db(conn)
        conn.close()

    skip_existing = not args.clean
    include_variants = not args.no_variants

    # Dispatch
    if args.starters:
        seed_starters(skip_existing=skip_existing,
                      include_variants=include_variants)
    elif args.gen:
        seed(ids_for_gens(args.gen), skip_existing=skip_existing,
             include_variants=include_variants)
    else:
        seed(list(range(1, 1026)), skip_existing=skip_existing,
             include_variants=include_variants)


if __name__ == "__main__":
    main()
