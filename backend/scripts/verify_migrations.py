#!/usr/bin/env python3
"""
Check that every table `supabase/migrations/*.sql` declares actually exists in
the configured Supabase project.

Migrations here are applied by hand through the SQL editor. Nothing records
which files have run, so the presence of a file in the repo is not evidence
that its schema is live — and the failure mode is quiet: the backend boots,
the page renders, and only the write fails. This reads the migrations, works
out which tables they are supposed to leave behind, and asks the project.

Two rewrites are accounted for, because a naive `CREATE TABLE` scan reports
both as missing:

  * `RENAME TO` — 007 renames `community_likes` to `community_post_votes`, so
    the old name is *expected* to be absent.
  * `DROP TABLE` — a table dropped by a later migration than the one that
    created it is likewise expected to be absent.

Usage:
    python scripts/verify_migrations.py           # report
    python scripts/verify_migrations.py --json    # machine-readable

Exit code is 1 when a table is missing, so CI can gate on it.
"""

import argparse
import json
import os
import re
import sys
from typing import Dict, List, Set, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings  # noqa: E402
from services.supabase_service import get_supabase  # noqa: E402

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MIGRATIONS_DIR = os.path.join(_REPO_ROOT, "supabase", "migrations")

# `public.` is optional and the quoting is inconsistent across the files, so the
# schema qualifier and any quotes are stripped after the match rather than
# encoded in the pattern.
_CREATE_RE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\"\w.]+)", re.IGNORECASE)
_RENAME_RE = re.compile(
    r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?([\"\w.]+)\s+RENAME\s+TO\s+([\"\w.]+)",
    re.IGNORECASE,
)
_DROP_RE = re.compile(r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?([\"\w.]+)", re.IGNORECASE)


def _clean(name: str) -> str:
    """Strip quoting and the schema qualifier from a matched identifier."""
    return name.replace('"', "").split(".")[-1].strip().lower()


def migration_files() -> List[str]:
    """Every migration, in the order their numeric prefix says they run."""
    if not os.path.isdir(MIGRATIONS_DIR):
        raise SystemExit(f"No migrations directory at {MIGRATIONS_DIR}")
    return sorted(f for f in os.listdir(MIGRATIONS_DIR) if f.endswith(".sql"))


def expected_tables() -> Tuple[Set[str], Dict[str, str], List[str]]:
    """
    Replay the migrations on paper.

    Returns the set of tables that should exist afterwards, a map of each
    retired table to the reason it is gone, and any numbering gaps found in the
    filenames — a gap usually means a migration was written, applied, and then
    lost before it reached the repo.
    """
    live: Set[str] = set()
    retired: Dict[str, str] = {}
    files = migration_files()

    for filename in files:
        with open(os.path.join(MIGRATIONS_DIR, filename), encoding="utf-8") as fh:
            sql = fh.read()

        # Order within a file matters: 005 drops `community_likes` and then
        # recreates it, and the net effect is that the table exists.
        for match in _DROP_RE.finditer(sql):
            table = _clean(match.group(1))
            live.discard(table)
            retired[table] = f"dropped by {filename}"

        for match in _CREATE_RE.finditer(sql):
            table = _clean(match.group(1))
            live.add(table)
            retired.pop(table, None)

        for match in _RENAME_RE.finditer(sql):
            old, new = _clean(match.group(1)), _clean(match.group(2))
            live.discard(old)
            live.add(new)
            retired[old] = f"renamed to {new} by {filename}"

    return live, retired, _numbering_gaps(files)


def _numbering_gaps(files: List[str]) -> List[str]:
    """Prefixes missing from an otherwise contiguous 001..NNN sequence."""
    numbers = sorted(int(f.split("_", 1)[0]) for f in files if f.split("_", 1)[0].isdigit())
    if not numbers:
        return []
    return [f"{n:03d}" for n in range(numbers[0], numbers[-1]) if n not in set(numbers)]


def table_exists(client, table: str) -> bool:
    """
    True when the project answers a zero-row read of `table`.

    A missing table surfaces as PostgREST's PGRST205 ("Could not find the
    table"). Any other failure is a connectivity or permission problem and is
    re-raised rather than reported as a missing table.
    """
    try:
        client.table(table).select("*").limit(0).execute()
        return True
    except Exception as exc:  # noqa: BLE001 — the message is the signal here
        text = str(exc)
        if "PGRST205" in text or "does not exist" in text or "Could not find the table" in text:
            return False
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = parser.parse_args()

    expected, retired, gaps = expected_tables()
    client = get_supabase()

    present = sorted(t for t in expected if table_exists(client, t))
    missing = sorted(set(expected) - set(present))
    # A retired table that is still there is harmless but worth knowing about:
    # it means the rename or drop never ran and the old copy is still holding
    # rows nothing reads.
    lingering = sorted(t for t in retired if table_exists(client, t))

    if args.json:
        print(
            json.dumps(
                {
                    "project": settings.SUPABASE_URL,
                    "expected": sorted(expected),
                    "present": present,
                    "missing": missing,
                    "lingering": lingering,
                    "numbering_gaps": gaps,
                },
                indent=2,
            )
        )
        return 1 if missing else 0

    print(f"Project: {settings.SUPABASE_URL}")
    print(f"Migrations: {len(migration_files())} file(s) in supabase/migrations/\n")

    for table in sorted(expected):
        print(f"  {'OK     ' if table in present else 'MISSING'}  {table}")

    if retired:
        print("\nRetired by a later migration (absence is correct):")
        for table, reason in sorted(retired.items()):
            note = "  <- still present!" if table in lingering else ""
            print(f"  {table} — {reason}{note}")

    if gaps:
        print(f"\nNumbering gap: {', '.join(gaps)} — a migration may be missing from the repo.")

    if missing:
        print(f"\n{len(missing)} table(s) missing. Apply the migration(s) that create them.")
        return 1

    print("\nEvery expected table is present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
