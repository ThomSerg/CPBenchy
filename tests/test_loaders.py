import pytest

import cpbenchy
from cpbenchy.config import UsageError
from cpbenchy.spec import Instance
from cpbenchy.testing import DATA

KNAPSACK = DATA / "knapsack.opb"


class WithoutItem(cpbenchy.Loader):
    """CPMpy's OPB loader, then forbid one item: the optimum gets worse."""

    def __init__(self, item):
        self.item = item

    def load(self, instance):
        model = super().load(instance)
        from cpmpy.transformations.get_variables import get_variables_model

        [var] = [v for v in get_variables_model(model) if v.name == self.item]
        model += ~var
        return model


class Squares(cpbenchy.Loader):
    """No files: builds a model from the instance's metadata."""

    def load(self, instance):
        import cpmpy as cp

        x = cp.intvar(1, 100, name="x")
        return cp.Model(x * x >= instance.metadata["at_least"], minimize=x)


def test_loader_object_from_the_api(benchtester):
    default, without_x2 = (
        benchtester.run(KNAPSACK, quiet=True),
        benchtester.run(KNAPSACK, loader=WithoutItem("x2"), quiet=True),
    )
    assert default[0].objective == -9 and default[0].loader is None
    assert without_x2[0].objective == -8 and without_x2[0].loader == "WithoutItem('x2')"
    assert default[0].run_id != without_x2[0].run_id  # both are kept, side by side
    assert len(cpbenchy.load(benchtester.out)) == 2


def test_loader_from_the_command_line(benchtester):
    path = benchtester.makefile(
        "loaders.py",
        """
        import cpbenchy

        class Minimizing(cpbenchy.Loader):
            def __init__(self, bound):
                self.bound = bound

            def load(self, instance):
                model = super().load(instance)
                model += model.objective_ >= self.bound  # a lower bound on the objective
                return model
        """,
    )
    outcome = benchtester.run_cli(
        "run", str(KNAPSACK), "-s", "ortools", "-t", "10", "-o", "out", "--loader", f"{path}:Minimizing(bound=-7)"
    )
    assert outcome.ret == 0, outcome.stderr
    assert outcome.results[0].loader == "Minimizing(bound=-7)"
    assert outcome.results[0].objective == -7


def test_loader_for_instances_without_files(benchtester):
    instances = [Instance(path=f"squares/{n}", name=f"squares-{n}", metadata={"at_least": n}) for n in (10, 50)]
    results = benchtester.run(instances, loader=Squares, quiet=True)
    assert sorted(r.objective for r in results) == [4, 8]


def test_loader_mistakes_are_usage_errors(benchtester):
    with pytest.raises(UsageError, match="can't load the loader"):
        benchtester.run(KNAPSACK, loader="no_such_module:Loader", quiet=True)
    with pytest.raises(UsageError, match="not a cpbenchy.Loader"):
        benchtester.run(KNAPSACK, loader="collections:OrderedDict", quiet=True)
