"""Run the experiments of a runexp config with cpbenchy, and keep runexp's result directories.

    python main.py config.json results/
    python main.py config.json results/ --jobs 4 --memory-limit 4096

Running it again only runs the experiments that have no result directory yet.
"""

import argparse
import json

from cpbenchy_runner import CpbenchyRunner

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("config", help="a runexp config: JSON, unravelled into experiments")
    parser.add_argument("output", help="runexp's output directory")
    parser.add_argument("--jobs", type=int, default=1, help="runs in parallel (default: %(default)s)")
    parser.add_argument("--memory-limit", type=int, default=-1, help="MiB per run, unless the config sets one")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)
    runner = CpbenchyRunner(func=None, output=args.output, memory_limit=args.memory_limit)
    runner.run_batch(config, parallel=args.jobs > 1, num_workers=args.jobs)
