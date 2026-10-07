# Examples

Each example is a single file to copy and adapt; `tests/test_examples.py` runs all of them.

Competition output (XCSP3, PB, MaxSAT, SAT), checking and saving solutions, and model statistics are
built in, in `cpbenchy.observers`; the docs' Library section lists everything ready to use:

```sh
cpbenchy run xcsp3/*.xml.lzma -s ortools -t 60 -p "cpbenchy.observers:XCSP3Output(checker='checker.jar')"
cpbenchy run instances/ -s ortools -t 60 -p cpbenchy.observers:CheckSolutions -p cpbenchy.observers:SaveSolution
```

**Plugins**

| | |
|---|---|
| [plugins/sqlite_store.py](plugins/sqlite_store.py) | also store results in an SQLite database |

**Scripts**, using the Python API

| | |
|---|---|
| [scripts/param_sweep.py](scripts/param_sweep.py) | tune OR-Tools: several parameter settings in one `Experiment`, results as they come |
| [scripts/formulations.py](scripts/formulations.py) | compare formulations of your own model on generated instances, without instance files |
| [scripts/analyze.py](scripts/analyze.py) | scores, the virtual best solver, and a cactus plot, with pandas |

**Integrations**, with other experiment tools

| | |
|---|---|
| [runexp/](runexp/) | run the experiments of a [runexp](https://github.com/IgnaceBleukx/Run-Experiments) config with cpbenchy, keeping runexp's result folders |

`data/` has tiny instances for trying the competition observers.
