import cpbenchy
from cpbenchy.spec import Instance, Limits, RunSpec
from cpbenchy.testing import DATA


def test_instance_name_drops_format_and_compression_extensions():
    assert Instance.from_path("a/b/foo.opb.xz").name == "foo"
    assert Instance.from_path("foo.xml.lzma").name == "foo"
    assert Instance.from_path("foo").name == "foo"


def test_run_id_ignores_where_the_instance_lives_if_its_dataset_is_known():
    a = RunSpec(Instance("/x/foo.opb", "foo", dataset="pb"), "ortools", Limits(10))
    b = RunSpec(Instance("/y/foo.opb", "foo", dataset="pb"), "ortools", Limits(10))
    c = RunSpec(Instance("/y/foo.opb", "foo", dataset="pb"), "ortools", Limits(10), seed=1)
    assert a.run_id == b.run_id != c.run_id


def test_spec_round_trips_through_json_dict():
    spec = RunSpec(Instance("foo.opb", "foo", metadata={"k": 1}), "exact", Limits(5, 1024), {"p": 1}, 3, 2)
    assert RunSpec.from_dict(spec.to_dict()) == spec


def test_run_stores_one_record_per_run(tmp_path):
    instances = [DATA / "knapsack.opb", DATA / "unsat.opb", DATA / "sat.opb", DATA / "knapsack_xz.opb.xz"]
    results = cpbenchy.run(instances, solvers=["ortools"], time_limit=20, out=tmp_path)

    by_instance = {r.instance: r for r in results}
    assert by_instance["knapsack"].status == "optimal"
    assert by_instance["knapsack"].objective == -9
    assert by_instance["knapsack_xz"].objective == -9
    assert by_instance["unsat"].status == "unsat"
    assert by_instance["sat"].status == "feasible"
    assert all(r.solved for r in results)
    assert all(r.parse_s is not None and r.walltime_s for r in results)
    assert cpbenchy.load(tmp_path) == results


def test_worker_error_is_a_result_not_a_crash(tmp_path):
    results = cpbenchy.run([DATA / "knapsack.opb"], solvers=["no-such-solver"], time_limit=20, out=tmp_path)
    assert results[0].status == "error"
    assert "no-such-solver" in results[0].error
