import cpbenchy
from cpbenchy.cli import main


def test_version(capsys):
    assert main(["--version"]) == 0
    assert cpbenchy.__version__ in capsys.readouterr().out


def test_unknown_command_is_a_usage_error(capsys):
    assert main(["frobnicate"]) == 2
    assert "unknown command" in capsys.readouterr().err
