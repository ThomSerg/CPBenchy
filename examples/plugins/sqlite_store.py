"""Also store results in an SQLite database, e.g. to collect many experiments in one place, or to query
them with SQL.

    cpbenchy run instances/ -s ortools -t 60 -p examples/plugins/sqlite_store.py          # results.db
    cpbenchy run instances/ -s ortools -t 60 -p "examples/plugins/sqlite_store.py:SqliteStore('all.db')"
    sqlite3 results.db "select solver, count(*) from runs where status = 'optimal' group by solver"

A table `runs` gets one row per run, keyed by run id (so a rerun replaces the row), with the main fields
as columns and the whole record as JSON in `record`.
"""

import json
import sqlite3

import cpbenchy

COLUMNS = ["instance", "dataset", "solver", "loader", "seed", "status", "objective", "walltime_s", "memory_mib"]


class SqliteStore(cpbenchy.Observer):
    def __init__(self, path="results.db"):
        self.path = path

    def on_session_start(self, session):
        self.db = sqlite3.connect(self.path)
        self.db.execute(f"CREATE TABLE IF NOT EXISTS runs (run_id PRIMARY KEY, {', '.join(COLUMNS)}, record)")

    def on_result(self, run, result):
        values = [result.run_id, *(getattr(result, c) for c in COLUMNS), json.dumps(result.to_dict(), default=str)]
        placeholders = ", ".join("?" * len(values))
        self.db.execute(f"INSERT OR REPLACE INTO runs VALUES ({placeholders})", values)
        self.db.commit()

    def on_session_end(self, session):
        self.db.close()
