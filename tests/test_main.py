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
