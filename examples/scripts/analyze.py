"""Analyse a results directory with pandas: a score table, the virtual best solver, and a cactus plot.

    python examples/scripts/analyze.py results/xcsp3-cop [--plot cactus.png]

Needs pandas (and matplotlib for --plot). The results are a plain table with one row per run, so any
analysis is a few lines of pandas; this is a starting point to copy.
"""

import argparse

import pandas as pd

import cpbenchy
from cpbenchy.scoring import par


def scores(df: pd.DataFrame) -> pd.DataFrame:
    """Per solver: solved instances, and the PAR-2 score (the time if solved, else twice the limit)."""
    table = df.groupby("solver").agg(runs=("run_id", "size"), solved=("solved", "sum"), par2=("par2", "sum"))
    return table.sort_values(["solved", "par2"], ascending=[False, True])


def virtual_best(df: pd.DataFrame) -> pd.DataFrame:
    """Per instance, the fastest solver that solved it: what a perfect portfolio would do."""
    solved = df[df.solved]
    best = solved.loc[solved.groupby("instance").walltime_s.idxmin(), ["instance", "solver", "walltime_s"]]
    return best.set_index("instance").sort_index()


def cactus(df: pd.DataFrame, path: str) -> None:
    """Solved instances (x) within a time (y), per solver: further right and lower is better."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 4.5))
    for solver, runs in df[df.solved].groupby("solver"):
        times = runs.walltime_s.sort_values().reset_index(drop=True)
        ax.plot(times.index + 1, times.values, marker="o", markersize=3, label=solver)
    ax.set(xlabel="instances solved", ylabel="wall time (s)", yscale="log")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=150)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out", help="a cpbenchy output directory")
    parser.add_argument("--plot", metavar="PNG", help="write a cactus plot here")
    args = parser.parse_args(argv)

    results = cpbenchy.load(args.out)
    df = results.to_pandas().assign(par2=[par(r) for r in results])

    print("Scores\n", scores(df), "\n", sep="")
    vbs = virtual_best(df)
    print(f"Virtual best solver: {len(vbs)} solved, {vbs.walltime_s.sum():.1f}s")
    print(vbs.solver.value_counts().rename("fastest on").to_string(), "\n")
    if args.plot:
        cactus(df, args.plot)
        print(f"cactus plot: {args.plot}")


if __name__ == "__main__":
    main()
