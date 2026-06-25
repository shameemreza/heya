"""End-to-end: a real Agent runs review_changes; the reviewer emits two findings,
the verifier confirms one and refutes the other, and the verdict keeps only the
confirmed one (the verify gate works over the real parallel machinery)."""
import threading

import heya.review as review_mod
from heya.agent import Agent
from heya.llm_client import ChatResult, ToolCall
from heya.subagents import SUBAGENT_FRAMING


class ThreadSafeFakeClient:
    """Dispatches by message content (children run concurrently)."""
    def __init__(self):
        self._lock = threading.Lock()
        self.calls = []

    def chat_stream(self, messages, tools=None, on_text=None):
        with self._lock:
            self.calls.append([dict(m) for m in messages])
        system = messages[0]["content"]
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        has_tool_result = any(m["role"] == "tool" for m in messages)
        if SUBAGENT_FRAMING[:24] in system:
            if "adversarial verifier" in last_user:
                # confirm the real one, refute the spurious one
                if "real sqli" in last_user:
                    result = ChatResult(content="VERDICT: real\ngrounding: $_GET into query")
                else:
                    result = ChatResult(content="VERDICT: false-positive\ngrounding: escaped")
            else:  # reviewer
                result = ChatResult(content=(
                    "### FINDING\nfile: a.php\nline: 5\nseverity: Blocker\ncategory: security\n"
                    "title: real sqli\nevidence: wpdb query on $_GET\nsuggestion: prepare\n### END\n"
                    "### FINDING\nfile: b.php\nline: 9\nseverity: High\ncategory: security\n"
                    "title: spurious xss\nevidence: maybe\nsuggestion: escape\n### END\n"))
        elif not has_tool_result:  # parent: call review_changes
            result = ChatResult(content=None, tool_calls=[ToolCall(
                id="1", name="review_changes", arguments='{"target": "branch"}')])
        else:  # parent: final
            result = ChatResult(content="done reviewing")
        if result.content and on_text:
            on_text(result.content)
        return result


class _AllowAll:
    def check(self, name, detail, label=""):
        return True


def test_review_pipeline_end_to_end(tmp_path, monkeypatch):
    # Inject a non-empty diff so the pipeline proceeds without a real git repo.
    monkeypatch.setattr(review_mod, "git_diff",
                        lambda target, **kw: "diff --git a/a.php b/a.php\n+$wpdb->query($_GET['id'])\n")
    client = ThreadSafeFakeClient()
    agent = Agent(client, allowed_roots=[tmp_path], cwd=tmp_path, approval=_AllowAll(),
                  self_review=False)
    answer = agent.run("review the branch")

    assert answer == "done reviewing"
    # The review_changes tool result (in the parent's final turn) is the verdict:
    tool_msg = next(m for m in client.calls[-1] if m["role"] == "tool")
    verdict = tool_msg["content"]
    assert "real sqli" in verdict          # confirmed finding kept
    assert "spurious xss" not in verdict   # refuted finding dropped
    assert "Blocker" in verdict


def test_review_clean_diff_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(review_mod, "git_diff",
                        lambda target, **kw: "diff --git a/a.php b/a.php\n+echo esc_html($x);\n")

    class CleanClient(ThreadSafeFakeClient):
        def chat_stream(self, messages, tools=None, on_text=None):
            with self._lock:
                self.calls.append([dict(m) for m in messages])
            system = messages[0]["content"]
            has_tool_result = any(m["role"] == "tool" for m in messages)
            if SUBAGENT_FRAMING[:24] in system:
                return ChatResult(content="NO FINDINGS")
            if not has_tool_result:
                return ChatResult(content=None, tool_calls=[ToolCall(
                    id="1", name="review_changes", arguments='{"target": "branch"}')])
            return ChatResult(content="all good")

    client = CleanClient()
    agent = Agent(client, allowed_roots=[tmp_path], cwd=tmp_path, approval=_AllowAll(),
                  self_review=False)
    agent.run("review the branch")
    tool_msg = next(m for m in client.calls[-1] if m["role"] == "tool")
    assert "nothing blocks" in tool_msg["content"].lower()


def test_security_review_flags_real_sqli_drops_guarded(tmp_path, monkeypatch):
    # Diff has a real SQLi (source $_GET into $wpdb->query, no prepare) and a guarded
    # query. The security reviewer flags both; the verifier confirms the SQLi and
    # refutes the guarded one. Only the SQLi survives.
    monkeypatch.setattr(review_mod, "git_diff", lambda target, **kw: (
        "diff --git a/p.php b/p.php\n"
        "+$wpdb->query(\"DELETE FROM t WHERE id = \" . $_GET['id']);\n"
        "+$wpdb->query($wpdb->prepare(\"DELETE FROM t WHERE id = %d\", $safe));\n"))

    class SecClient:
        def __init__(self):
            self._lock = __import__("threading").Lock()
            self.calls = []
        def chat_stream(self, messages, tools=None, on_text=None):
            with self._lock:
                self.calls.append([dict(m) for m in messages])
            system = messages[0]["content"]
            last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
            has_tool_result = any(m["role"] == "tool" for m in messages)
            if SUBAGENT_FRAMING[:24] in system:
                if "adversarial verifier" in last_user:
                    if "unprepared sqli" in last_user:
                        return ChatResult(content="VERDICT: real\ngrounding: $_GET into query, no prepare")
                    return ChatResult(content="VERDICT: false-positive\ngrounding: uses $wpdb->prepare")
                # security reviewer: report one real + one spurious
                return ChatResult(content=(
                    "### FINDING\nfile: p.php\nline: 1\nseverity: Blocker\ncategory: sqli\n"
                    "title: unprepared sqli\nevidence: $_GET['id'] into $wpdb->query, no prepare\n"
                    "suggestion: use prepare\n### END\n"
                    "### FINDING\nfile: p.php\nline: 2\nseverity: Blocker\ncategory: sqli\n"
                    "title: guarded query flagged\nevidence: second query\nsuggestion: n/a\n### END\n"))
            if not has_tool_result:
                return ChatResult(content=None, tool_calls=[ToolCall(
                    id="1", name="review_changes",
                    arguments='{"target": "branch", "focus": "security"}')])
            return ChatResult(content="security review done")

    client = SecClient()
    agent = Agent(client, allowed_roots=[tmp_path], cwd=tmp_path, approval=_AllowAll(),
                  self_review=False)
    agent.run("security-check this")
    tool_msg = next(m for m in client.calls[-1] if m["role"] == "tool")
    verdict = tool_msg["content"]
    assert "unprepared sqli" in verdict        # real SQLi confirmed → kept
    assert "guarded query flagged" not in verdict  # guarded one refuted → dropped
    assert "Blocker" in verdict
