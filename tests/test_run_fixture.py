from premode.fixture import run_fixture


def test_run_fixture_passes_without_real_codex():
    result = run_fixture()
    assert result["fixture_repo"]
    assert result["dry_run"]["command"][-1] == "-"
    assert result["dry_run"]["stdin"] == "<compiled-packet-on-stdin>"
