from brandguard import __version__
from brandguard.cli import main


def test_setup_creates_home_database_and_queue(brandguard_home, capsys):
    assert main(["setup", "--skip-browser"]) == 0
    for path in ("brandguard.db", "queue.db", "data", "logs"):
        assert (brandguard_home / path).exists(), path
    assert str(brandguard_home.resolve()) in capsys.readouterr().out


def test_version(capsys):
    assert main(["version"]) == 0
    assert capsys.readouterr().out.strip() == __version__
