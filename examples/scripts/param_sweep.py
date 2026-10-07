"""Tune a solver: run OR-Tools with several parameter settings on the same instances, then compare.

    python examples/scripts/param_sweep.py instances/ --out results/sweep --time-limit 60 --jobs 4

Each setting is one `add()` with its own parameters and cores, all in one experiment, so they share
the output directory: run it again after adding a setting, and only the new runs happen. Results stream
in as runs finish; at the end, a table shows per setting how many instances were solved and how fast.
"""

import argparse

import cpbenchy

SETTINGS = {
    # name: (cores, OR-Tools parameters)
    "1 worker": (1, {"num_search_workers": 1}),
    "1 worker, no LP": (1, {"num_search_workers": 1, "linearization_level": 0}),
    "1 worker, full LP": (1, {"num_search_workers": 1, "linearization_level": 2}),
    "4 workers": (4, {"num_search_workers": 4}),
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sources", nargs="+", help="instance files, directories or glob patterns")
    parser.add_argument("--out", default="results/param-sweep")
    parser.add_argument("--time-limit", type=float, default=60)
    parser.add_argument("--jobs", type=int, default=1)
    args = parser.parse_args(argv)

    exp = cpbenchy.Experiment(args.out, time_limit=args.time_limit, jobs=args.jobs, quiet=True)
    for cores, params in SETTINGS.values():
        exp.add(*args.sources, solver="ortools", params=params, cores=cores)

    print(f"{len(exp.runs)} runs; results in {args.out}")
    for result in exp.iter_results():
        print(f"  {setting_of(result):<20} {result.instance:<30} {result.status:<9} {result.walltime_s:7.2f}s")

    print(summary(exp.results()))


def setting_of(result) -> str | None:
    return next(
        (n for n, (cores, params) in SETTINGS.items() if (cores, params) == (result.cores, result.params)), None
    )


def summary(results) -> str:
    rows = []
    for name in SETTINGS:
        runs = [r for r in results if setting_of(r) == name]
        solved = [r for r in runs if r.solved]
        time_solved = sum(r.walltime_s for r in solved)
        rows.append(f"{name:<20} solved {len(solved):>3}/{len(runs):<3}  time on solved {time_solved:8.1f}s")
    return "\n".join(rows)


if __name__ == "__main__":
    main()
