"""Load your own instance files: knapsack problems as JSON.

    cpbenchy run examples/data/*.json -s ortools -s exact -t 60 --loader examples/loaders/knapsack_json.py:KnapsackJSON

A file holds {"capacity": ..., "items": [{"weight": ..., "value": ...}, ...]}. The loader builds the
CPMpy model in the worker, so building it is measured as `parse_s`, like loading any other format.
"""

import json

import cpbenchy


class KnapsackJSON(cpbenchy.Loader):
    def load(self, instance):
        import cpmpy as cp

        data = json.loads(self.read(instance.path))  # read() also handles .xz, .gz, ... files
        weights = [item["weight"] for item in data["items"]]
        values = [item["value"] for item in data["items"]]
        take = cp.boolvar(shape=len(weights), name="take")
        model = cp.Model(cp.sum(take * weights) <= data["capacity"])
        model.maximize(cp.sum(take * values))
        return model
