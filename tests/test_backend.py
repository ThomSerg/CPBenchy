from cpbenchy import Instance, Limits, RunSpec
from cpbenchy.backend import BackendResult, Submission, run
from cpbenchy.result import Results
from cpbenchy.testing import DATA


def test_each_key_gets_the_shared_measurement(benchtester):
    spec = RunSpec(Instance.from_path(DATA / "knapsack.opb"), "ortools", Limits(10))
    submissions = [
        Submission(spec, key="row-1", metadata={"trial": 1}),
        Submission(spec, key="row-2", metadata={"trial": 2}),
    ]
    seen = []

    results = run(submissions, executor="subprocess", quiet=True, out=benchtester.out, on_result=seen.append)

    assert results == seen
    assert [(item.key, item.metadata) for item in results] == [("row-1", {"trial": 1}), ("row-2", {"trial": 2})]
    assert results[0].result.run_id == results[1].result.run_id == spec.run_id
    assert results[0].result.to_dict() == results[1].result.to_dict()
    assert results[0].result.status != "error"
    assert results[0].log is not None
    assert len(Results.load(benchtester.out)) == 1


def test_backend_result_carries_the_log(benchtester):
    spec = RunSpec(Instance.from_path(DATA / "sat.opb"), "ortools", Limits(10))
    [item] = run([Submission(spec, key="only")], executor="subprocess", quiet=True, out=benchtester.out)
    assert isinstance(item, BackendResult)
    assert item.key == "only"
    assert item.log is not None
