"""
models/pokemon.py
 
Pokemon dataclass and database access layer.
 
Provides:
  - Pokemon        : immutable dataclass representing a single DB row
  - PokemonDB      : context-manager-friendly DB access object
"""

import sqlite3
import os
from dataclasses import dataclass
from typing import Optional

# Default DB path — can be overridden via PokemonDB(db_path=...)
DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "pokemon.db"
)


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Pokemon:
    """
    Immutable representation of a single Pokemon record.

    `id` and `form` together form the unique identifier:
      - id   : National Pokedex number (shared across regional variants)
      - form : 'default' for the standard form, or a region slug such as
               'alola', 'galar', 'hisui', 'paldea' for regional variants

    `name` is the full PokeAPI slug (e.g. 'typhlosion-hisui') and is the
    value used during prime derivation — ensuring variants produce distinct
    primes from their base forms.
    """
    id:             int
    form:           str
    name:           str
    type_primary:   str
    type_secondary: Optional[str]
    height:         float           # metres
    weight:         float           # kg
    base_stat_total: int
    generation:     int
    color:          str

    @property
    def types(self) -> tuple[str, ...]:
        """Return types as a tuple, omitting None for single-type Pokemon."""
        if self.type_secondary:
            return (self.type_primary, self.type_secondary)
        return (self.type_primary,)

    @property
    def is_default_form(self) -> bool:
        return self.form == "default"

    @property
    def display_name(self) -> str:
        """Human-readable name with form label for variants."""
        if self.is_default_form:
            return self.name.title()
        return f"{self.name.replace('-', ' ').title()}"

    def __str__(self) -> str:
        types = "/".join(self.types)
        form_label = f" [{self.form}]" if not self.is_default_form else ""
        return (
            f"#{self.id:04d}{form_label} {self.display_name} "
            f"({types}, Gen {self.generation}, "
            f"{self.height}m, {self.weight}kg, BST {self.base_stat_total})"
        )

# ---------------------------------------------------------------------------
# Row factory
# ---------------------------------------------------------------------------


def _row_to_pokemon(row: sqlite3.Row) -> Pokemon:
    return Pokemon(
        id=row["id"],
        form=row["form"],
        name=row["name"],
        type_primary=row["type_primary"],
        type_secondary=row["type_secondary"],
        height=row["height"],
        weight=row["weight"],
        base_stat_total=row["base_stat_total"],
        generation=row["generation"],
        color=row["color"],
    )

# ---------------------------------------------------------------------------
# Database access
# ---------------------------------------------------------------------------


class PokemonDB:
    """
    Lightweight database access object for the local Pokemon SQLite database.

    Supports use as a context manager:
        with PokemonDB() as db:
            results = db.find_by(type_primary="fire")

    Or manual open/close:
        db = PokemonDB()
        db.open()
        ...
        db.close()
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = os.path.abspath(db_path)
        self._conn: Optional[sqlite3.Connection] = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def open(self):
        if self._conn is not None:
            return
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(
                f"Pokemon database not found at {self.db_path}. "
                "Run scripts/seed_db.py to populate it."
            )
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *_):
        self.close()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError(
                "Database is not open. Call open() or use as a context manager.")
        return self._conn

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, pokedex_id: int, form: str = "default") -> Optional[Pokemon]:
        """
        Fetch a single Pokemon by its (id, form) composite key.
        Returns None if not found.
        """
        row = self.conn.execute(
            "SELECT * FROM pokemon WHERE id = ? AND form = ?",
            (pokedex_id, form)
        ).fetchone()
        return _row_to_pokemon(row) if row else None

    def get_by_name(self, name: str) -> Optional[Pokemon]:
        """
        Fetch a single Pokemon by its exact PokeAPI slug name.
        Returns None if not found.
        """
        row = self.conn.execute(
            "SELECT * FROM pokemon WHERE name = ?",
            (name.lower(),)
        ).fetchone()
        return _row_to_pokemon(row) if row else None

    def all(self) -> list[Pokemon]:
        """Return every Pokemon in the database, ordered by id then form."""
        rows = self.conn.execute(
            "SELECT * FROM pokemon ORDER BY id, form"
        ).fetchall()
        return [_row_to_pokemon(r) for r in rows]

    def find_by(self, **kwargs) -> list[Pokemon]:
        """
        Flexible field-based query. Pass any combination of column names
        as keyword arguments to filter by exact match.

        Supported fields:
            id, form, type_primary, type_secondary, height, weight,
            base_stat_total, generation, color

        Example:
            db.find_by(type_primary="fire", generation=2)
            db.find_by(color="blue", type_secondary=None)

        Returns a list of matching Pokemon (empty list if none match).
        """
        ALLOWED_FIELDS = {
            "id", "form", "type_primary", "type_secondary",
            "height", "weight", "base_stat_total", "generation", "color"
        }

        invalid = set(kwargs) - ALLOWED_FIELDS
        if invalid:
            raise ValueError(
                f"Invalid filter field(s): {invalid}. Allowed: {ALLOWED_FIELDS}")

        if not kwargs:
            return self.all()

        clauses = []
        values = []

        for field, value in kwargs.items():
            if value is None:
                clauses.append(f"{field} IS NULL")
            else:
                clauses.append(f"{field} = ?")
                values.append(value)

        where = " AND ".join(clauses)
        rows = self.conn.execute(
            f"SELECT * FROM pokemon WHERE {where} ORDER BY id, form",
            values
        ).fetchall()

        return [_row_to_pokemon(r) for r in rows]

    def count(self) -> int:
        """Return the total number of records in the database."""
        return self.conn.execute("SELECT COUNT(*) FROM pokemon").fetchone()[0]

    def generations(self) -> list[int]:
        """Return a sorted list of all generation numbers present in the DB."""
        rows = self.conn.execute(
            "SELECT DISTINCT generation FROM pokemon ORDER BY generation"
        ).fetchall()
        return [r[0] for r in rows]
