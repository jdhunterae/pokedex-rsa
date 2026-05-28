#!/usr/bin/env python3
"""
ui/serve.py

Entry point for `poke-rsa-ui`. Checks the database, then launches the
Flask development server.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def main():
    from pokedex_rsa.models.pokemon import PokemonDB, DEFAULT_DB_PATH

    db_path = os.path.abspath(DEFAULT_DB_PATH)
    count   = 0

    if os.path.exists(db_path):
        try:
            with PokemonDB(db_path=db_path) as db:
                count = db.count()
        except Exception:
            count = 0

    if count == 0:
        print("⚠  No Pokemon database found.")
        print("   The app will open a setup page to initialize it.")
    else:
        print(f"✓  Database ready ({count} Pokemon).")

    print("   Starting Pokedex RSA UI on http://127.0.0.1:5000")
    print("   Press Ctrl+C to stop.\n")

    from ui.app import app
    app.run(debug=False, port=5000, host="127.0.0.1")


if __name__ == "__main__":
    main()