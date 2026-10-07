"""Compare formulations of your own model, on generated instances: no instance files at all.

    python examples/scripts/formulations.py --sizes 8 32 64 --solvers ortools exact --time-limit 30

The instances are just sizes (in their `metadata`), and a `Loader` with an argument builds the model in
the worker: N-Queens with AllDifferent constraints, or with a != between every pair of queens. Each
formulation is one `add()` with its own loader; results record the loader, so they stay apart.
"""

import argparse

import cpbenchy
from cpbenchy import Instance


class NQueens(cpbenchy.Loader):
    def __init__(self, formulation):
        self.formulation = formulation  # "alldifferent" or "pairwise"

    def load(self, instance):
        import cpmpy as cp

        n = instance.metadata["n"]
        queens = cp.intvar(0, n - 1, shape=n, name="queen")  # the column of the queen in each row
        diagonals = [queens[i] + i for i in range(n)], [queens[i] - i for i in range(n)]
        if self.formulation == "alldifferent":
            return cp.Model(cp.AllDifferent(queens), *(cp.AllDifferent(d) for d in diagonals))
        return cp.Model(
            [queens[i] != queens[j] for i in range(n) for j in range(i + 1, n)],
            [d[i] != d[j] for d in diagonals for i in range(n) for j in range(i + 1, n)],
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sizes", type=int, nargs="+", default=[8, 32, 64])
    parser.add_argument("--solvers", nargs="+", default=["ortools"])
    parser.add_argument("--time-limit", type=float, default=30)
    parser.add_argument("--out", default="results/nqueens")
    args = parser.parse_args(argv)

    instances = [Instance(path=f"nqueens/{n}", name=f"nqueens-{n}", metadata={"n": n}) for n in args.sizes]
    exp = cpbenchy.Experiment(args.out, time_limit=args.time_limit, quiet=True)
    for formulation in ("alldifferent", "pairwise"):
        exp.add(instances, solvers=args.solvers, loader=NQueens(formulation))

    for r in sorted(exp.run(), key=lambda r: (r.instance, r.solver, r.loader)):
        times = f"build {r.parse_s:6.2f}s  solve {r.solve_s:6.2f}s"
        print(f"{r.instance:<12} {r.solver:<8} {r.loader:<26} {r.status:<9} {times}")


if __name__ == "__main__":
    main()
