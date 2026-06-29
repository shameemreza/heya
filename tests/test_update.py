from heya.update import is_newer


def test_is_newer_true_when_latest_greater():
    assert is_newer("0.0.3", "0.0.2") is True
    assert is_newer("1.0.1", "1.0") is True
    assert is_newer("0.1.0", "0.0.9") is True


def test_is_newer_false_when_same_or_older():
    assert is_newer("0.0.2", "0.0.2") is False
    assert is_newer("0.0.1", "0.0.2") is False
    assert is_newer("1.0", "1.0.1") is False


def test_is_newer_handles_prerelease_and_garbage():
    # numeric part wins; trailing suffix is ignored for the compare
    assert is_newer("0.2.0rc1", "0.1.9") is True
    # malformed input never raises, returns False
    assert is_newer("not-a-version", "0.0.2") is False
    assert is_newer(None, "0.0.2") is False


def test_cache_roundtrip(tmp_path):
    from heya.update import read_cache, write_cache

    p = tmp_path / "update-cache.json"
    write_cache({"checked": 123.0, "latest": "0.0.3"}, p)
    assert read_cache(p) == {"checked": 123.0, "latest": "0.0.3"}


def test_read_cache_missing_or_malformed_returns_empty(tmp_path):
    from heya.update import read_cache

    assert read_cache(tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("}{ not json")
    assert read_cache(bad) == {}


def test_update_notice_disabled_returns_none_and_no_fetch(tmp_path):
    from heya.update import update_notice

    called = {"n": 0}

    def fetcher():
        called["n"] += 1
        return "9.9.9"

    out = update_notice("0.0.2", enabled=False, fetcher=fetcher,
                        cache_file=tmp_path / "c.json")
    assert out is None
    assert called["n"] == 0  # disabled does no work


def test_update_notice_returns_newer_from_fresh_cache(tmp_path):
    from heya.update import update_notice, write_cache

    p = tmp_path / "c.json"
    write_cache({"checked": 1000.0, "latest": "0.0.3"}, p)
    # clock is just past the cache time, so the cache is fresh (no refresh spawned)
    out = update_notice("0.0.2", clock=lambda: 1001.0, cache_file=p, spawn=True,
                        fetcher=lambda: "ignored")
    assert out == "0.0.3"


def test_update_notice_none_when_cache_not_newer(tmp_path):
    from heya.update import update_notice, write_cache

    p = tmp_path / "c.json"
    write_cache({"checked": 1000.0, "latest": "0.0.2"}, p)
    assert update_notice("0.0.2", clock=lambda: 1001.0, cache_file=p) is None


def test_refresh_writes_cache(tmp_path):
    from heya.update import _refresh, read_cache

    p = tmp_path / "c.json"
    _refresh(clock=lambda: 555.0, fetcher=lambda: "0.0.5", cache_file=p)
    assert read_cache(p) == {"checked": 555.0, "latest": "0.0.5"}
