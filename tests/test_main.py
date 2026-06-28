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
