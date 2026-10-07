import pytest

from cpbenchy.executors import runexec_problem

pytest_plugins = ["cpbenchy.testing"]


def pytest_collection_modifyitems(items):
    for item in items:
        if item.get_closest_marker("runexec") and runexec_problem():
            item.add_marker(pytest.mark.skip(reason=f"runexec unavailable: {runexec_problem()}"))
