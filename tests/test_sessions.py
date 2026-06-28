from heya import sessions


def _msgs():
    return [{"role": "system", "content": "sys"},
            {"role": "user", "content": "Why does checkout fail on WP 6.5 with a long description here"}]


def test_save_and_load_roundtrip(tmp_path):
    data = {"id": "abc123", "title": "t", "created": "t0", "updated": "t1",
            "profile": "local", "cwd": "/x", "session_tokens": 5, "weak_tokens": 0,
            "messages": _msgs()}
    p = sessions.save_session(data, sessions_dir=tmp_path)
    assert p.exists()
    assert (p.stat().st_mode & 0o777) == 0o600
    got = sessions.load_session("abc123", sessions_dir=tmp_path)
    assert got["messages"] == _msgs() and got["profile"] == "local"


def test_load_accepts_id_prefix(tmp_path):
    sessions.save_session({"id": "abcdef", "messages": _msgs()}, sessions_dir=tmp_path)
    assert sessions.load_session("abc", sessions_dir=tmp_path)["id"] == "abcdef"


def test_list_sessions_newest_first(tmp_path):
    sessions.save_session({"id": "a", "updated": "2026-01-01", "messages": _msgs()}, sessions_dir=tmp_path)
    sessions.save_session({"id": "b", "updated": "2026-02-01", "messages": _msgs()}, sessions_dir=tmp_path)
    ids = [s["id"] for s in sessions.list_sessions(sessions_dir=tmp_path)]
    assert ids == ["b", "a"]


def test_latest_session_id(tmp_path):
    sessions.save_session({"id": "a", "updated": "2026-01-01", "messages": _msgs()}, sessions_dir=tmp_path)
    sessions.save_session({"id": "b", "updated": "2026-02-01", "messages": _msgs()}, sessions_dir=tmp_path)
    assert sessions.latest_session_id(sessions_dir=tmp_path) == "b"


def test_derive_title_truncates_first_user_message():
    t = sessions.derive_title(_msgs())
    assert t.startswith("Why does checkout fail") and len(t) <= 60


def test_malformed_file_is_skipped(tmp_path):
    (tmp_path / "bad.json").write_text("{not json")
    assert sessions.list_sessions(sessions_dir=tmp_path) == []
    assert sessions.load_session("bad", sessions_dir=tmp_path) is None


def test_load_missing_returns_none(tmp_path):
    assert sessions.load_session("nope", sessions_dir=tmp_path) is None
    assert sessions.latest_session_id(sessions_dir=tmp_path) is None


def test_load_ambiguous_prefix_returns_none(tmp_path):
    sessions.save_session({"id": "abcuno", "messages": _msgs()}, sessions_dir=tmp_path)
    sessions.save_session({"id": "abcdos", "messages": _msgs()}, sessions_dir=tmp_path)
    assert sessions.load_session("abc", sessions_dir=tmp_path) is None
