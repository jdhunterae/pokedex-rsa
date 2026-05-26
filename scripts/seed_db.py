#!/usr/bin/env python3
"""
seed_db.py - Populate the local Pokemon SQLite database from PokeAPI.

Usage:
    python seed_db.py                  # Append all Pokemon, skip existing
    python seed_db.py --gen 1          # Append Gen 1 only, skip existing
    python seed_db.py --gen 1 --gen 2  # Append Gen 1 and Gen 2, skip existing
    python seed_db.py --starters       # Append all 81 starter-line Pokemon
    python seed_db.py --clean          # Wipe DB, then pull everything
    python seed_db.py --clean --gen 1  # Wipe DB, then pull Gen 1 only
    python seed_db.py --clean --starters  # Wipe DB, then pull starters
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

# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------


def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pokemon (
            id              INTEGER PRIMARY KEY,
            name            TEXT    NOT NULL UNIQUE,
            type_primary    TEXT    NOT NULL,
            type_secondary  TEXT,
            height          REAL    NOT NULL,
            weight          REAL    NOT NULL,
            base_stat_total INTEGER NOT NULL,
            generation      INTEGER NOT NULL,
            color           TEXT    NOT NULL
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
    # name is like "generation-i", "generation-ii", etc.
    roman = data["name"].split("-")[1].upper()
    roman_map = {
        "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5,
        "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10
    }
    return roman_map.get(roman, 0)


def fetch_pokemon_record(pokedex_id):
    """
    Pull all required fields for a single Pokemon by Pokedex ID.
    Returns a dict ready for DB insertion, or None on failure.
    """
    try:
        # Primary pokemon endpoint
        poke_data = fetch(f"{POKEAPI_BASE}/pokemon/{pokedex_id}")
        time.sleep(REQUEST_DELAY)

        # Species endpoint for generation and color
        species_data = fetch(poke_data["species"]["url"])
        time.sleep(REQUEST_DELAY)

        name = poke_data["name"]
        types = [t["type"]["name"] for t in poke_data["types"]]
        type_primary = types[0] if len(types) > 0 else None
        type_secondary = types[1] if len(types) > 1 else None

        # PokeAPI stores height in decimetres, weight in hectograms
        height = poke_data["height"] / 10.0   # convert to metres
        weight = poke_data["weight"] / 10.0   # convert to kg

        base_stat_total = sum(s["base_stat"] for s in poke_data["stats"])

        generation = get_generation_number(species_data["generation"]["url"])
        time.sleep(REQUEST_DELAY)

        color = species_data["color"]["name"]

        return {
            "id": pokedex_id,
            "name": name,
            "type_primary": type_primary,
            "type_secondary": type_secondary,
            "height": height,
            "weight": weight,
            "base_stat_total": base_stat_total,
            "generation": generation,
            "color": color,
        }

    except Exception as e:
        print(f"  ERROR fetching #{pokedex_id}: {e}")
        return None


def insert_record(conn, record, skip_existing=True):
    """
    Insert a Pokemon record. Returns 'inserted', 'skipped', or 'error'.
    """
    if skip_existing:
        existing = conn.execute(
            "SELECT id FROM pokemon WHERE id = ?", (record["id"],)
        ).fetchone()
        if existing:
            return "skipped"

    try:
        conn.execute("""
            INSERT OR REPLACE INTO pokemon
                (id, name, type_primary, type_secondary, height, weight,
                 base_stat_total, generation, color)
            VALUES
                (:id, :name, :type_primary, :type_secondary, :height, :weight,
                 :base_stat_total, :generation, :color)
        """, record)
        conn.commit()
        return "inserted"
    except sqlite3.Error as e:
        print(f"  DB error for #{record['id']}: {e}")
        return "error"

# ---------------------------------------------------------------------------
# Evolution chain resolution
# ---------------------------------------------------------------------------


def get_evolution_chain_ids(base_id):
    """
    Given a base-stage Pokedex ID, return all IDs in its evolution chain
    in order (base → middle → final). Returns a list of 1-3 IDs.
    """
    try:
        species_data = fetch(f"{POKEAPI_BASE}/pokemon-species/{base_id}")
        time.sleep(REQUEST_DELAY)

        chain_data = fetch(species_data["evolution_chain"]["url"])
        time.sleep(REQUEST_DELAY)

        ids = []
        node = chain_data["chain"]
        while node:
            species_name = node["species"]["name"]
            # Resolve species name to Pokedex ID
            sp = fetch(f"{POKEAPI_BASE}/pokemon-species/{species_name}")
            time.sleep(REQUEST_DELAY)
            ids.append(sp["id"])
            node = node["evolves_to"][0] if node["evolves_to"] else None

        return ids

    except Exception as e:
        print(f"  ERROR resolving evolution chain for #{base_id}: {e}")
        return [base_id]  # Fall back to just the base

# ---------------------------------------------------------------------------
# Generation range helpers
# ---------------------------------------------------------------------------


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


def ids_for_gens(gens):
    ids = []
    for gen in gens:
        if gen not in GEN_RANGES:
            print(f"Warning: unknown generation {gen}, skipping.")
            continue
        start, end = GEN_RANGES[gen]
        ids.extend(range(start, end + 1))
    return ids


def all_ids():
    return list(range(1, 1026))

# ---------------------------------------------------------------------------
# Main seed routine
# ---------------------------------------------------------------------------


def seed(ids_to_fetch, skip_existing=True):
    conn = get_connection()
    init_db(conn)

    total = len(ids_to_fetch)
    inserted = skipped = errors = 0

    print(f"\nFetching {total} Pokemon records...")
    print(
        f"Mode: {'append (skip existing)' if skip_existing else 'overwrite'}\n")

    for i, pokedex_id in enumerate(ids_to_fetch, 1):
        print(f"[{i}/{total}] #{pokedex_id}", end=" ", flush=True)

        if skip_existing:
            existing = conn.execute(
                "SELECT name FROM pokemon WHERE id = ?", (pokedex_id,)
            ).fetchone()
            if existing:
                print(f"→ skipped ({existing[0]} already in DB)")
                skipped += 1
                continue

        record = fetch_pokemon_record(pokedex_id)
        if record is None:
            errors += 1
            continue

        result = insert_record(conn, record, skip_existing=False)
        if result == "inserted":
            print(f"→ {record['name']} (Gen {record['generation']}, "
                  f"{record['type_primary']}"
                  f"{'/' + record['type_secondary'] if record['type_secondary'] else ''}, "
                  f"BST {record['base_stat_total']})")
            inserted += 1
        else:
            errors += 1

    conn.close()

    print(f"\n{'='*50}")
    print(
        f"Done. Inserted: {inserted} | Skipped: {skipped} | Errors: {errors}")
    print(f"Database: {os.path.abspath(DB_PATH)}")


def seed_starters(skip_existing=True):
    print("Resolving evolution chains for all starters...")
    all_ids_to_fetch = []

    for base_id in STARTER_BASE_IDS:
        print(f"  Resolving chain for #{base_id}...", end=" ", flush=True)
        chain_ids = get_evolution_chain_ids(base_id)
        print(f"→ {chain_ids}")
        all_ids_to_fetch.extend(chain_ids)

    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for pid in all_ids_to_fetch:
        if pid not in seen:
            seen.add(pid)
            deduped.append(pid)

    print(
        f"\nResolved {len(deduped)} unique Pokemon across all starter lines.\n")
    seed(deduped, skip_existing=skip_existing)

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
        help="Pull all three evolution stages for every gen's starters (81 Pokemon)."
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="Wipe the existing database before pulling. Cannot be undone."
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

    # Dispatch
    if args.starters:
        seed_starters(skip_existing=skip_existing)
    elif args.gen:
        ids = ids_for_gens(args.gen)
        seed(ids, skip_existing=skip_existing)
    else:
        seed(all_ids(), skip_existing=skip_existing)


if __name__ == "__main__":
    main()
