"""The worker: the measured process that loads, transforms and solves one instance.

    python -m cpbenchy.worker JOB.json

The parent writes JOB.json (the run spec, the event file, the plugins to load) and starts this under an
executor's limits. The worker appends JSON events to the event file as it goes, and ends with a `result`
event holding its report. If it is killed, the executor's measurement says why.

Everything in this package runs inside the measured process, possibly in another environment than the
parent (an older solver version), so it imports only the standard library, pluggy and CPMpy, and stays
Python 3.10 compatible. It never redirects stdout or stderr: those go to the run's log file.
"""

THREAD_ENV = {"OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
"""Set for every worker (unless already set): numpy's linear algebra libraries otherwise start a thread per
CPU when CPMpy is imported, which costs a run seconds of CPU time it doesn't need. Solvers' own threads are
set through their parameters (`--cores`)."""
