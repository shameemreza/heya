import io
import sys

from heya.main import build_parser, run_cli


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
    monkeypatch.setattr(main_mod, "LLMClient", lambda profile: object())
    args = main_mod.build_parser().parse_args(["hi"])
    agent = main_mod._default_make_agent(args)
    assert agent.process_registry is not None
    assert agent.playground_session is not None
    agent.close()  # must tear down registry + sessions without error


def test_default_make_agent_wires_mcp_runtime(monkeypatch):
    import heya.main as main_mod
    monkeypatch.setattr(main_mod, "LLMClient", lambda profile: object())
    monkeypatch.setattr(main_mod, "load_mcp_servers", lambda *a, **k: ())
    args = main_mod.build_parser().parse_args([])
    agent = main_mod._default_make_agent(args)
    try:
        assert agent.mcp_runtime is not None
    finally:
        agent.close()


def test_default_make_agent_wires_llm_into_runtime(monkeypatch):
    import heya.main as main_mod
    monkeypatch.setattr(main_mod, "LLMClient", lambda profile: object())
    monkeypatch.setattr(main_mod, "load_mcp_servers", lambda *a, **k: ())
    args = main_mod.build_parser().parse_args([])
    agent = main_mod._default_make_agent(args)
    try:
        # the runtime received the same client object the agent uses
        assert agent.mcp_runtime._callback_deps.llm_client is agent.client
    finally:
        agent.close()
