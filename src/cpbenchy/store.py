"""An output directory:

    results.jsonl              one RunResult per line, appended as runs finish
    run.json                   provenance of the latest session: settings, versions, host, plugins
    logs/<run_id>.log          the worker's stdout and stderr
    logs/<run_id>.events.jsonl the worker's events, ending with its report
    logs/<run_id>.job.json     what the worker was asked to do (`cpbenchy check` rebuilds the model from it)

Appending one line per finished run keeps results readable while a session runs, safe if it crashes,
and resumable: runs whose id is already in results.jsonl are done.
"""

import json
from pathlib import Path
from typing import Any

from cpbenchy.result import Results, RunResult


class Store:
    def __init__(self, out: str | Path):
        self.out = Path(out)
        self.results_file = self.out / "results.jsonl"
        self.logs = self.out / "logs"

    def open(self) -> "Store":
        self.logs.mkdir(parents=True, exist_ok=True)
        return self

    def load(self) -> Results:
        return Results.load(self.results_file)

    def finished_ids(self) -> set[str]:
        return {r.run_id for r in self.load()}

    def append(self, result: RunResult) -> None:
        with open(self.results_file, "a") as f:
            f.write(json.dumps(result.to_dict(), default=str) + "\n")

    def rewrite(self, results: Results) -> None:
        """Replace all stored results (atomically), e.g. after adding to their `extra`."""
        tmp = self.results_file.with_suffix(".jsonl.tmp")
        tmp.write_text("".join(json.dumps(r.to_dict(), default=str) + "\n" for r in results))
        tmp.replace(self.results_file)

    def write_provenance(self, data: dict[str, Any]) -> None:
        (self.out / "run.json").write_text(json.dumps(data, indent=2, default=str) + "\n")

    def job_file(self, run_id: str) -> Path:
        return self.logs / f"{run_id}.job.json"

    def log_file(self, run_id: str) -> Path:
        return self.logs / f"{run_id}.log"

    def events_file(self, run_id: str) -> Path:
        return self.logs / f"{run_id}.events.jsonl"
