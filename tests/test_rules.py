"""Rules (`--rules`): named, shareable settings."""

import json

import pytest

import cpbenchy
from cpbenchy.config import UsageError, make_config
from cpbenchy.rules import Rules, builtin
from cpbenchy.testing import DATA

KNAPSACK = DATA / "knapsack.opb"

MY_RULES = """
name = "my-setup"
description = "what we agreed on"
url = "https://example.org/setup"

[settings]
time-limit = 20
cpu-time-limit = 10
mem-limit = 2048
cores = 1
terminate = true
grace = 3
plugins = ["cpbenchy.observers:ModelSize"]
"""


@pytest.mark.parametrize("rules", builtin(), ids=lambda r: r.name)
def test_every_builtin_rules_file_is_valid(rules):
    config = make_config([], rules=rules.name)
    assert config.rules.name == rules.name and not config.deviations
    assert config.getoption("time_limit") == rules.settings["time-limit"]
    assert config.getoption("terminate") is True


def test_rules_from_a_file_set_options_and_plugins(benchtester):
    path = benchtester.makefile("my.toml", MY_RULES)
    config = make_config(["--rules", str(path)])
    get = config.getoption
    assert (get("time_limit"), get("cputime_limit_s"), get("mem_limit_mib"), get("grace_s")) == (20, 10, 2048, 3)
    assert any("ModelSize" in name for name, _ in config.pluginmanager.list_name_plugin())
    assert config.rules_label == "my-setup"


def test_explicit_options_win_and_are_recorded():
    config = make_config(["-t", "5", "--scale", "0.5"], rules="xcsp3-2025")
    assert config.getoption("time_limit") == 5
    assert config.deviations == {"time-limit": 5, "scale": 0.5}
    assert config.rules_label == "xcsp3-2025 (modified)"


def test_rules_override_the_config_file_but_not_the_command_line(benchtester):
    benchtester.makefile("cpbenchy.toml", 'rules = "pb26"\ntime-limit = 5\njobs = 2\n')
    from cpbenchy.config import read_config_file

    config = make_config([], defaults=read_config_file())
    assert config.getoption("time_limit") == 3600 and config.getoption("jobs") == 2
    assert not config.deviations


def test_bad_rules_are_usage_errors(benchtester):
    with pytest.raises(UsageError, match="no rules named"):
        Rules.load("nope")
    with pytest.raises(UsageError, match="need a `name`"):
        Rules.from_toml("[settings]\ntime-limit = 1\n")
    path = benchtester.makefile("bad.toml", 'name = "bad"\n[settings]\ntime-limt = 1\n')
    with pytest.raises(UsageError, match="unknown option 'time-limt' in the rules"):
        make_config([], rules=str(path))


def test_runs_record_their_rules(benchtester):
    path = benchtester.makefile("my.toml", MY_RULES)
    outcome = benchtester.run_cli("run", str(KNAPSACK), "-s", "ortools", "-o", "out", "--rules", str(path))
    assert outcome.ret == 0, outcome.stderr
    [result] = outcome.results
    assert result.rules == "my-setup"
    assert (result.time_limit_s, result.cputime_limit_s, result.mem_limit_mib) == (20, 10, 2048)
    assert result.extra["n_constraints"] == 1  # the rules' plugin
    provenance = json.loads((benchtester.out / "run.json").read_text())
    assert provenance["rules"]["name"] == "my-setup" and provenance["rules"]["deviations"] == {}
    assert "rules my-setup: what we agreed on" in outcome.stdout


def test_scale_and_modified_runs_from_python(benchtester):
    path = benchtester.makefile("my.toml", MY_RULES)
    exp = cpbenchy.Experiment(benchtester.out, rules=str(path), quiet=True, args=["--scale", "0.5"])
    exp.add(KNAPSACK, solver="ortools")
    exp.add(DATA / "sat.opb", solver="ortools", time_limit=7)  # its own limit
    results = {r.instance: r for r in exp.run()}
    assert (results["knapsack"].time_limit_s, results["knapsack"].cputime_limit_s) == (10, 5)
    assert results["knapsack"].rules == "my-setup (modified)"  # scaled
    assert results["sat"].time_limit_s == 3.5 and results["sat"].rules == "my-setup (modified)"


def test_cli_lists_and_shows_rules(benchtester):
    listing = benchtester.run_cli("rules")
    assert listing.ret == 0 and "xcsp3-2025 " in listing.stdout and "pb26 " in listing.stdout
    shown = benchtester.run_cli("rules", "pb26")
    assert Rules.from_toml(shown.stdout).settings["cpu-time-limit"] == 3600


def test_too_much_memory_for_the_machine_says_the_rules_set_it(benchtester, monkeypatch):
    import cpbenchy.session

    monkeypatch.setattr(cpbenchy.session, "total_memory_mib", lambda: 32000)
    with pytest.raises(UsageError, match="the memory limit is that of the rules xcsp3-2025; give a lower one with -m"):
        cpbenchy.run(KNAPSACK, solvers=["ortools"], rules="xcsp3-2025", args=["--scale", "0.05"], quiet=True)
    [result] = cpbenchy.run(
        KNAPSACK, solvers=["ortools"], rules="xcsp3-2025", mem_limit_mib=4096, args=["--scale", "0.01"], quiet=True
    )
    assert result.mem_limit_mib == 4096 and result.rules == "xcsp3-2025 (modified)"
