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


def test_port_check_detects_a_listening_server():
    import socket

    from brandguard.cli import _port_is_free

    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        assert _port_is_free("127.0.0.1", port) is False
    assert _port_is_free("127.0.0.1", port) is True
