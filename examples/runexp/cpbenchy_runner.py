"""Use cpbenchy to measure the experiments of a runexp config (https://github.com/IgnaceBleukx/Run-Experiments).

runexp unravels the config and keeps one result directory per experiment; cpbenchy runs each experiment
as one solver run, under its limits, and the stats go into that experiment's directory. See main.py.

Each unravelled config needs a `solver`, an `instance` (one file; a glob in the config becomes one
experiment per file) and a `time_limit` in seconds. Optional: `mem_limit_mib` (else the runner's
`memory_limit`), `params` (passed to `solve()`), `seed`, `cores` and `loader` (a reference, as for
`--loader`).
"""

import json
import os

from runexp import Runner
from runexp.utils import unravel_dict

from cpbenchy import Instance, Limits, RunSpec
from cpbenchy.backend import Submission, run

# The stats written as a .txt file each (with `solved`), for runexp's results_to_df; stats.json has all of them.
STATS = ("status", "objective", "walltime_s", "cputime_s", "memory_mib", "parse_s", "solve_s")


class CpbenchyRunner(Runner):
    def make_kwargs(self, config):  # cpbenchy runs the solver, so there is no experiment function to call
        return dict(config)

    def run_batch(self, config, parallel=False, num_workers=None, show_progress=True):
        """Measure every unravelled config that has no result yet, `num_workers` at a time if `parallel`."""
        configs = self.filter_experiments(unravel_dict(config))
        print(f"{len(configs)} experiments to run")
        jobs = (num_workers or os.cpu_count() - 1) if parallel else 1
        self.measure(configs, jobs)

    def run_one(self, config):
        self.measure([config], jobs=1)

    def measure(self, configs, jobs):
        submissions = [Submission(self.spec(config), key=str(i)) for i, config in enumerate(configs)]
        # cpbenchy limits and measures each run itself, so runexp's own memory limit and process pool aren't used
        run(submissions, jobs=jobs, on_result=lambda item: self.store(configs[int(item.key)], item))

    def spec(self, config):
        """What cpbenchy measures for one config."""
        default_mem = self.memlimit if self.memlimit > 0 else None
        return RunSpec(
            Instance.from_path(config["instance"]),
            config["solver"],
            Limits(time_s=float(config["time_limit"]), mem_mib=config.get("mem_limit_mib", default_mem)),
            params=config.get("params", {}),
            seed=config.get("seed"),
            cores=config.get("cores", 1),
            loader=config.get("loader"),
        )

    def store(self, config, item):
        """Write one run's stats into a new result directory, next to its config."""
        record = item.result.to_dict()
        artifacts = {name: record[name] for name in STATS if record[name] is not None}
        artifacts["solved"] = item.result.solved
        artifacts["stats.json"] = json.dumps(record)  # runexp writes a key with an extension as it is
        if item.log is not None:
            artifacts["solver.log"] = item.log
        self.save_result(config, artifacts, self.mkdir())
