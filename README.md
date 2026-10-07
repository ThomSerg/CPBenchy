<div align="center">

# cpbenchy

**Benchmark [CPMpy](https://github.com/CPMpy/cpmpy) solvers under proper resource limits,<br>
change anything using plugins.**

[![Docs](https://img.shields.io/badge/docs-docs.cpbenchy.com-0a7bbb)](https://docs.cpbenchy.com/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/ThomSerg/CPBenchy/blob/main/LICENSE)
[![Status: alpha](https://img.shields.io/badge/status-alpha-orange)](https://docs.cpbenchy.com/getting-started/installation/#alpha)
[![Version](https://img.shields.io/badge/version-0.1.0.dev0-blue)](https://github.com/ThomSerg/CPBenchy/blob/main/pyproject.toml)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](https://github.com/ThomSerg/CPBenchy/blob/main/pyproject.toml)
[![Platform: Linux](https://img.shields.io/badge/platform-linux-lightgrey?logo=linux&logoColor=white)](https://docs.cpbenchy.com/getting-started/installation/)
[![Built on CPMpy](https://img.shields.io/badge/built%20on-CPMpy-4b8bbe)](https://github.com/CPMpy/cpmpy)
[![Measured with BenchExec](https://img.shields.io/badge/measured%20with-BenchExec-2e7d32)](https://github.com/sosy-lab/benchexec)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

**Documentation: [docs.cpbenchy.com](https://docs.cpbenchy.com/)**

<img src="https://github.com/ThomSerg/CPBenchy/raw/main/.github/assets/cpbenchy-run.svg" alt="A cpbenchy run: OR-Tools and Z3 on seven PB24 instances, each run's status and time, and a summary per solver with a PAR-2 score" width="760">

</div>

> [!WARNING]
> cpbenchy is in **alpha** (version 0.x): commands, options, the Python API and the result format may
> still change between versions. Pin the version you depend on.

Reliably benchmark CPMpy solvers. Every run gets its own process, its own cores and resource limits, get back one record per run: status, objective, times and memory.

From the command line or from the Python API. Interrupt it, and resume later.

### Key features

* **[Measured properly](https://docs.cpbenchy.com/guides/limits/)**: BenchExec's `runexec` with cgroups, CPU time and peak memory, pinned cores
* **Any instance**: XCSP3, OPB, WCNF, DIMACS, MPS and more, compressed or not, any CPMpy dataset
* **Any solver**: every solver CPMpy supports
* **[Competition-ready](https://docs.cpbenchy.com/guides/rules/)**: follow the XCSP3 and PB competitions' rules and output
* **[Checked answers](https://docs.cpbenchy.com/library/check-solutions/)**: every solution checked against the model
* **[Analysis-friendly](https://docs.cpbenchy.com/guides/results/)**: one record per run, access as a pandas DataFrame, get PAR-k scores
* **[Extensible](https://docs.cpbenchy.com/plugins/overview/)**: your own measurements, formats, ... a flexible plugin architecture

## Install

```sh
pip install cpbenchy
cpbenchy doctor          # check install
```

Linux, Python 3.10+. For reliable limits, install BenchExec with cgroups v2; see
[Installation](https://docs.cpbenchy.com/getting-started/installation/).

## Quick start

```sh
# a benchmark set: the PB24 optimisation instances (or any instance files of your own)
python -c "from cpmpy.tools.datasets import OPBDataset; OPBDataset(root='data', year=2024, track='OPT-LIN', download=True)"

cpbenchy run data/opb/ -s ortools -s exact -t 60 --limit 10   # two solvers, ten instances, 60 s each
cpbenchy show                                                 # the summary, from cpbenchy-results/
```

Run it again without `--limit`, and only the missing runs get performed.
Creat your [first benchmark](https://docs.cpbenchy.com/getting-started/first-benchmark/).

## From Python

```python
import cpbenchy

results = cpbenchy.run("data/opb/", solvers=["ortools", "exact"], time_limit=60)
results.to_pandas().groupby("solver").solved.sum()
```

For different settings per solver, results as they come in, or asyncio, see
[Experiments](https://docs.cpbenchy.com/guides/experiments/).

## Make it yours

Record anything about each run with an observer, a class following the observer pattern:

```python
class SolverTime(cpbenchy.Observer):
    def on_finish(self, ctx):                      # at the end of each run
        ctx.record("solver_time_s", ctx.solver.status().runtime)
```

Load your own formats, choose runs, or replace any step: see
[Extending cpbenchy](https://docs.cpbenchy.com/plugins/overview/).

## What's included

* **[Competition rules](https://docs.cpbenchy.com/guides/rules/)**: the limits, signals and output of the XCSP3 and PB competitions, or your own: `--rules xcsp3-2025`
* **[Competition output](https://docs.cpbenchy.com/library/#output)**: answers printed as the XCSP3, PB, MaxSAT and SAT competitions expect them
* **[Solution checking](https://docs.cpbenchy.com/library/check-solutions/)**: during the run, or afterwards on stored solutions: `cpbenchy check`
* **[PAR-k scores](https://docs.cpbenchy.com/library/par/)**: rank solvers as competitions do: `--par 2`
* **[Stopping at the limit](https://docs.cpbenchy.com/library/terminate/)**: SIGTERM at the limit, and the best solution so far: `--terminate`
* **[CPU time limits](https://docs.cpbenchy.com/guides/limits/)**, seeds, solver parameters, cores per run, and runs in parallel
* **[Experiments](https://docs.cpbenchy.com/guides/experiments/)** in Python: settings per solver, results as they come in, asyncio
* **[Competition submissions](https://docs.cpbenchy.com/guides/submissions/)** *(work in progress)*: a self-contained submission from rules and a solver
* **[From your framework](https://docs.cpbenchy.com/guides/backend/)** *(work in progress)*: cpbenchy measures, your framework decides and stores

The [library](https://docs.cpbenchy.com/library/) lists everything ready to use, and the
[examples](https://docs.cpbenchy.com/examples/) are there to copy.

## License

cpbenchy is licensed under the [Apache License 2.0](https://github.com/ThomSerg/CPBenchy/blob/main/LICENSE).
