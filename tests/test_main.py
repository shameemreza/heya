import io
import sys

import pytest

from heya.main import build_parser, run_cli
import heya.main as main_mod


class FakeAgent:
    def __init__(self):
        self.prompts = []
        self.messages = [{"role": "system", "content": "sys"}]

    def run(self, text):
        self.prompts.append(text)
        answer = f"answer to: {text}"
        sys.stdout.write(answer)  # simulate the agent streaming its reply live
        return answer


def test_parser_reads_task_and_flags():
    args = build_parser().parse_args(["do", "the", "thing", "--profile", "cloud", "--auto-approve"])
    assert args.task == ["do", "the", "thing"]
    assert args.profile == "cloud"
    assert args.auto_approve is True


def test_one_shot_runs_once_and_prints(capsys):
    agent = FakeAgent()
    code = run_cli(build_parser().parse_args(["say", "hi"]), make_agent=lambda args: agent, stdin=io.StringIO(""))
    assert code == 0
    assert agent.prompts == ["say hi"]
    assert "answer to: say hi" in capsys.readouterr().out


def test_interactive_runs_until_eof(capsys):
    agent = FakeAgent()
    stdin = io.StringIO("first\nsecond\n")  # then EOF
    code = run_cli(build_parser().parse_args([]), make_agent=lambda args: agent, stdin=stdin)
    assert code == 0
    assert agent.prompts == ["first", "second"]


def test_interactive_exits_on_quit_command(capsys):
    agent = FakeAgent()
    stdin = io.StringIO("hello\nquit\nnever\n")
    run_cli(build_parser().parse_args([]), make_agent=lambda args: agent, stdin=stdin)
    assert agent.prompts == ["hello"]


def test_run_cli_closes_agent(capsys):
    class ClosableAgent:
        def __init__(self):
            self.closed = False
            self.messages = []
        def run(self, text):
            return "ok"
        def close(self):
            self.closed = True

    import io
    agent = ClosableAgent()
    run_cli(build_parser().parse_args(["hi"]), make_agent=lambda args: agent, stdin=io.StringIO(""))
    assert agent.closed is True


def test_default_make_agent_builds_with_wp_wiring(monkeypatch, tmp_path):
    import heya.main as main_mod
    # avoid a real LLM client/network: stub it
    monkeypatch.setattr(main_mod, "LLMClient", lambda profile, **kw: object())
    args = main_mod.build_parser().parse_args(["hi"])
    agent = main_mod._default_make_agent(args)
    assert agent.process_registry is not None
    assert agent.playground_session is not None
    agent.close()  # must tear down registry + sessions without error


def test_default_make_agent_wires_mcp_runtime(monkeypatch):
    import heya.main as main_mod
    monkeypatch.setattr(main_mod, "LLMClient", lambda profile, **kw: object())
    monkeypatch.setattr(main_mod, "load_mcp_servers", lambda *a, **k: ())
    args = main_mod.build_parser().parse_args([])
    agent = main_mod._default_make_agent(args)
    try:
        assert agent.mcp_runtime is not None
    finally:
        agent.close()


def test_default_make_agent_wires_llm_into_runtime(monkeypatch):
    import heya.main as main_mod
    monkeypatch.setattr(main_mod, "LLMClient", lambda profile, **kw: object())
    monkeypatch.setattr(main_mod, "load_mcp_servers", lambda *a, **k: ())
    args = main_mod.build_parser().parse_args([])
    agent = main_mod._default_make_agent(args)
    try:
        # the runtime received the same client object the agent uses
        assert agent.mcp_runtime._callback_deps.llm_client is agent.client
    finally:
        agent.close()


# ---------------------------------------------------------------------------
# New tests: banner, slash commands, --version
# ---------------------------------------------------------------------------

class _FakeAgent:
    def __init__(self):
        self.messages = [{"role": "system", "content": "sys"}]
        self.session_tokens = 0
        self.weak_tokens = 0
        self.skills = {"foo": object()}
        self.agent_roles = {}
        self.ran = []

    def run(self, text):
        self.ran.append(text)
        return "ok"

    def close(self):
        pass


def _run(stdin_text):
    agent = _FakeAgent()
    args = build_parser().parse_args([])
    code = run_cli(args, make_agent=lambda a: agent, stdin=io.StringIO(stdin_text))
    return code, agent


def test_slash_quit_ends_loop():
    code, agent = _run("/quit\n")
    assert code == 0 and agent.ran == []


def test_slash_help_lists_and_continues():
    code, agent = _run("/help\nhello\n/quit\n")
    assert "hello" in agent.ran


def test_slash_clear_resets_messages():
    code, agent = _run("/clear\n/quit\n")
    assert len(agent.messages) == 1


def test_normal_input_runs_agent():
    code, agent = _run("do a thing\n/quit\n")
    assert agent.ran == ["do a thing"]


def test_version_flag():
    with pytest.raises(SystemExit) as e:
        main_mod.main(["--version"])
    assert e.value.code == 0


# ---------------------------------------------------------------------------
# Task-6 tests: first-run wizard routing and preflight gating
# ---------------------------------------------------------------------------

import types


def _agent_with_profile():
    """A FakeAgent that also exposes .client.profile, so preflight runs."""
    a = FakeAgent()
    a.client = types.SimpleNamespace(
        profile=types.SimpleNamespace(model="m", name="local"))
    return a


def test_init_token_routes_to_wizard(capsys):
    called = {"n": 0}

    def fake_init(**kw):
        called["n"] += 1
        return 0

    code = run_cli(build_parser().parse_args(["init"]),
                   make_agent=lambda args: FakeAgent(),
                   stdin=io.StringIO(""), init_fn=fake_init)
    assert code == 0 and called["n"] == 1


def test_fresh_install_launches_wizard(tmp_path, monkeypatch, capsys):
    # point config at a non-existent path so it's a "fresh install"
    monkeypatch.setattr(main_mod, "default_config_path", lambda: tmp_path / "none.toml")
    called = {"n": 0}

    def fake_init(**kw):
        called["n"] += 1
        return 0

    agent = FakeAgent()
    # no task, fresh config, auto_init on -> wizard runs, then REPL reads EOF
    code = run_cli(build_parser().parse_args([]),
                   make_agent=lambda args: agent,
                   stdin=io.StringIO(""), init_fn=fake_init, auto_init=True)
    assert called["n"] == 1


def test_no_auto_init_without_flag(tmp_path, monkeypatch):
    # the default (auto_init off) must NOT launch the wizard, even on a fresh
    # config -- this is what keeps the existing interactive tests valid.
    monkeypatch.setattr(main_mod, "default_config_path", lambda: tmp_path / "none.toml")
    called = {"n": 0}
    agent = FakeAgent()
    run_cli(build_parser().parse_args([]),
            make_agent=lambda args: agent, stdin=io.StringIO("hi\n"),
            init_fn=lambda **kw: called.__setitem__("n", called["n"] + 1) or 0)
    assert called["n"] == 0
    assert agent.prompts == ["hi"]


def test_one_shot_no_model_prints_hint_and_exits(tmp_path, monkeypatch, capsys):
    # a real, existing config so the fresh-install path is NOT taken
    cfg = tmp_path / "config.toml"
    cfg.write_text('[defaults]\nprofile = "local"\n')
    monkeypatch.setattr(main_mod, "default_config_path", lambda: cfg)
    monkeypatch.setattr(main_mod, "check_profile", lambda *a, **k: "unreachable")
    agent = _agent_with_profile()  # has .client.profile, so preflight is consulted
    code = run_cli(build_parser().parse_args(["do", "thing"]),
                   make_agent=lambda args: agent, stdin=io.StringIO(""))
    assert code == 1
    assert agent.prompts == []  # never ran the task
    assert "model" in capsys.readouterr().out.lower()


def test_one_shot_runs_when_model_ok(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[defaults]\nprofile = "local"\n')
    monkeypatch.setattr(main_mod, "default_config_path", lambda: cfg)
    monkeypatch.setattr(main_mod, "check_profile", lambda *a, **k: "ok")
    agent = _agent_with_profile()
    code = run_cli(build_parser().parse_args(["say", "hi"]),
                   make_agent=lambda args: agent, stdin=io.StringIO(""))
    assert code == 0 and agent.prompts == ["say hi"]


# ---------------------------------------------------------------------------
# Task 2 tests: slash commands /model, /new, /sessions, /resume, /save
# ---------------------------------------------------------------------------

from heya import sessions as sessions_mod


def _agent_with_state():
    from heya.config import Profile
    a = FakeAgent()
    a.cwd = "/tmp/x"
    a.session_id = "sid1"
    a.session_tokens = 7
    a.weak_tokens = 0
    profile = Profile(name="local", base_url="u", model="m", provider_type="local")
    a.client = types.SimpleNamespace(profile=profile)
    a.context_window = 8192
    return a


def test_slash_model_switch(monkeypatch):
    from heya.config import Profile
    profiles = {"local": Profile(name="local", base_url="u", model="m", provider_type="local"),
                "cloud": Profile(name="cloud", base_url="c", model="big", provider_type="api_key")}
    agent = _agent_with_state()
    ui = main_mod.UI(plain=True, write=lambda s: None)
    cont = main_mod._handle_slash("/model cloud", agent, ui, profiles=profiles)
    assert cont is True
    assert agent.client.profile.name == "cloud" and agent.context_window == profiles["cloud"].context_window


def test_slash_model_unknown_lists_and_keeps(capsys):
    from heya.config import Profile
    profiles = {"local": Profile(name="local", base_url="u", model="m", provider_type="local")}
    agent = _agent_with_state()
    ui = main_mod.UI(plain=True)
    main_mod._handle_slash("/model nope", agent, ui, profiles=profiles)
    assert agent.client.profile.name == "local"  # unchanged
    assert "local" in capsys.readouterr().out


def test_slash_new_resets_and_changes_id():
    agent = _agent_with_state()
    agent.messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "x"}]
    ui = main_mod.UI(plain=True, write=lambda s: None)
    main_mod._handle_slash("/new", agent, ui)
    assert agent.messages == [{"role": "system", "content": "s"}]
    assert agent.session_id != "sid1"


def test_slash_resume_loads_messages(tmp_path):
    sessions_mod.save_session(
        {"id": "old1", "messages": [{"role": "system", "content": "s"},
                                    {"role": "user", "content": "earlier"}]},
        sessions_dir=tmp_path)
    agent = _agent_with_state()
    ui = main_mod.UI(plain=True, write=lambda s: None)
    main_mod._handle_slash("/resume old1", agent, ui, sessions_dir=tmp_path)
    assert agent.session_id == "old1"
    assert any(m.get("content") == "earlier" for m in agent.messages)


def test_slash_sessions_lists(tmp_path, capsys):
    sessions_mod.save_session({"id": "s1", "title": "first thing", "updated": "2026-01-01",
                               "messages": []}, sessions_dir=tmp_path)
    agent = _agent_with_state()
    ui = main_mod.UI(plain=True)
    main_mod._handle_slash("/sessions", agent, ui, sessions_dir=tmp_path)
    assert "first thing" in capsys.readouterr().out


def test_slash_save_writes_with_title(tmp_path):
    agent = _agent_with_state()
    agent.messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]
    ui = main_mod.UI(plain=True, write=lambda s: None)
    main_mod._handle_slash("/save my title", agent, ui, sessions_dir=tmp_path,
                           created="t0", now=lambda: "t1")
    data = sessions_mod.load_session("sid1", sessions_dir=tmp_path)
    assert data["title"] == "my title" and data["session_tokens"] == 7


# ---------------------------------------------------------------------------
# Task 3 tests: auto-save and --continue/--resume flags
# ---------------------------------------------------------------------------


def test_autosave_after_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions_mod, "default_sessions_dir", lambda: tmp_path)
    monkeypatch.setattr(main_mod, "check_profile", lambda *a, **k: "ok")
    agent = _agent_with_state()
    agent.messages = [{"role": "system", "content": "s"}]
    run_cli(build_parser().parse_args([]), make_agent=lambda args: agent,
            stdin=io.StringIO("hello\n"))
    files = list(tmp_path.glob("*.json"))
    assert files, "a session file should be written after the turn"
    data = sessions_mod.load_session("sid1", sessions_dir=tmp_path)
    assert any(m.get("content") == "hello" for m in data["messages"]) or agent.prompts == ["hello"]


def test_continue_loads_latest(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions_mod, "default_sessions_dir", lambda: tmp_path)
    monkeypatch.setattr(main_mod, "check_profile", lambda *a, **k: "ok")
    sessions_mod.save_session({"id": "prev", "updated": "2026-01-01",
                               "messages": [{"role": "system", "content": "s"},
                                            {"role": "user", "content": "earlier"}]},
                              sessions_dir=tmp_path)
    agent = _agent_with_state()
    run_cli(build_parser().parse_args(["--continue"]), make_agent=lambda args: agent,
            stdin=io.StringIO(""))
    assert agent.session_id == "prev"
    assert any(m.get("content") == "earlier" for m in agent.messages)


def test_resume_unknown_id_starts_fresh(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sessions_mod, "default_sessions_dir", lambda: tmp_path)
    monkeypatch.setattr(main_mod, "check_profile", lambda *a, **k: "ok")
    agent = _agent_with_state()
    code = run_cli(build_parser().parse_args(["--resume", "ghost"]),
                   make_agent=lambda args: agent, stdin=io.StringIO(""))
    assert code == 0
    assert agent.session_id == "sid1"  # unchanged, fresh


# ---------------------------------------------------------------------------
# Task 4 tests: attachment handling and vision model warnings
# ---------------------------------------------------------------------------


def test_attachment_image_warns_non_vision(tmp_path, monkeypatch, capsys):
    img = tmp_path / "s.png"
    img.write_bytes(b"\x89PNGFAKE")
    agent = _agent_with_state()           # model "m" -> not vision
    agent.allowed_roots = [tmp_path]
    agent.cwd = tmp_path
    captured = {}
    agent.run = lambda content: captured.update(content=content) or "ok"
    ui = main_mod.UI(plain=True)
    content = main_mod._build_turn_content("see @s.png", agent, ui)
    assert isinstance(content, list) and any(b.get("type") == "image_url" for b in content)
    assert "cannot see images" in capsys.readouterr().out.lower()


def test_attachment_note_for_bad_path(tmp_path, capsys):
    agent = _agent_with_state()
    agent.allowed_roots = [tmp_path]
    agent.cwd = tmp_path
    ui = main_mod.UI(plain=True)
    content = main_mod._build_turn_content("see @/etc/shadow", agent, ui)
    assert content == "see @/etc/shadow"  # nothing attached
    assert "could not include" in capsys.readouterr().out.lower()


def test_slash_model_no_profiles(capsys):
    agent = _agent_with_state()
    ui = main_mod.UI(plain=True)
    main_mod._handle_slash("/model cloud", agent, ui, profiles={})
    assert "no profiles loaded" in capsys.readouterr().out.lower()
    assert agent.client.profile.name == "local"  # unchanged


def test_slash_resume_bare_resumes_latest(tmp_path):
    sessions_mod.save_session({"id": "newest", "updated": "2026-02-01",
                               "messages": [{"role": "system", "content": "s"},
                                            {"role": "user", "content": "latest one"}]},
                              sessions_dir=tmp_path)
    sessions_mod.save_session({"id": "older", "updated": "2026-01-01", "messages": []},
                              sessions_dir=tmp_path)
    agent = _agent_with_state()
    ui = main_mod.UI(plain=True, write=lambda s: None)
    main_mod._handle_slash("/resume", agent, ui, sessions_dir=tmp_path)
    assert agent.session_id == "newest"


def test_slash_resume_ignores_glued_token(tmp_path):
    sessions_mod.save_session({"id": "abc", "messages": [{"role": "system", "content": "s"}]},
                              sessions_dir=tmp_path)
    agent = _agent_with_state()
    ui = main_mod.UI(plain=True, write=lambda s: None)
    main_mod._handle_slash("/resumeabc", agent, ui, sessions_dir=tmp_path)
    assert agent.session_id == "sid1"  # not treated as a resume of "abc"


# ---------------------------------------------------------------------------
# Task 10 tests: background registry in session snapshot
# ---------------------------------------------------------------------------


def test_session_snapshot_includes_background(tmp_path):
    from heya.background import BackgroundRegistry
    from heya.main import _session_snapshot

    reg = BackgroundRegistry()

    def run(entry, on_text):
        return "built it"

    reg.start(run, task="build a plugin")
    import time
    time.sleep(0.1)

    class _FakeAgent:
        messages = [{"role": "user", "content": "hi"}]
        session_id = "s1"
        cwd = tmp_path
        background_registry = reg

    snap = _session_snapshot(_FakeAgent(), profile_name="p", created="t", updated="t")
    assert "background" in snap
    assert snap["background"] and snap["background"][0]["status"] == "done"


# ---------------------------------------------------------------------------
# Task 6 tests: heya update command dispatch
# ---------------------------------------------------------------------------


def test_update_command_dispatches(tmp_path):
    import argparse

    from heya.main import run_cli

    called = {"n": 0}

    def fake_update():
        called["n"] += 1
        return 0

    args = argparse.Namespace(task=["update"])
    code = run_cli(args, update_fn=fake_update)
    assert code == 0
    assert called["n"] == 1


# ---------------------------------------------------------------------------
# Task 6 (wp-integration) tests: connector construction contract
# ---------------------------------------------------------------------------


def test_build_wp_connector_from_config_and_credential(tmp_path):
    from heya.config import WPSiteConfig
    from heya.wpsite import WPClient, build_wp_connector

    cfg = WPSiteConfig(url="http://s.test", user="admin", env="dev")
    assert isinstance(build_wp_connector(cfg, "app-pass"), WPClient)
    assert build_wp_connector(WPSiteConfig(url="x", user="u", env="production"), "app-pass") is None


def test_wp_connect_command_dispatches(tmp_path):
    import argparse
    from heya.main import run_cli
    called = {"n": 0}
    def fake(stream=None):
        called["n"] += 1
        return 0
    assert run_cli(argparse.Namespace(task=["wp", "connect"]), wp_connect_fn=fake) == 0
    assert called["n"] == 1
