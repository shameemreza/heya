import threading
import time

from heya.approval import ApprovalPolicy, unified_file_diff


def test_reads_are_auto_approved():
    policy = ApprovalPolicy(approver=lambda name, detail: "no")
    assert policy.check("read_file", "read_file → a.txt") is True


def test_write_prompts_and_respects_yes():
    calls = []
    policy = ApprovalPolicy(approver=lambda name, detail: calls.append(name) or "yes")
    assert policy.check("write_file", "write_file → out.txt") is True
    assert calls == ["write_file"]


def test_write_denied_on_no():
    policy = ApprovalPolicy(approver=lambda name, detail: "no")
    assert policy.check("run_command", "run_command → rm -rf x") is False


def test_auto_approve_bypasses_prompt():
    policy = ApprovalPolicy(auto_approve=True, approver=lambda name, detail: "no")
    assert policy.check("write_file", "write_file → out.txt") is True


def test_always_allows_for_rest_of_session():
    # For command tools, "always" is scoped per-command (argv), not per-tool-name.
    # Each distinct command is prompted once; the same command is not prompted again.
    calls = []
    policy = ApprovalPolicy(approver=lambda name, detail: calls.append(name) or "always")
    assert policy.check("run_command", "run_command → ls") is True
    assert policy.check("run_command", "run_command → pwd") is True
    # Both calls reach the approver because "ls" and "pwd" are different commands.
    assert calls == ["run_command", "run_command"]


def test_browser_click_and_type_are_gated():
    denied = ApprovalPolicy(approver=lambda name, detail: "no")
    assert denied.check("browser_click", "browser_click → Go") is False
    assert denied.check("browser_type", "browser_type → Email") is False


def test_browser_navigate_is_not_gated():
    denied = ApprovalPolicy(approver=lambda name, detail: "no")
    assert denied.check("browser_navigate", "browser_navigate → https://x") is True


def _deny(name, detail):
    return "no"  # any prompt → denied, so only the allowlist can approve


def test_allowlist_auto_approves_matching_command():
    policy = ApprovalPolicy(approver=_deny, allow=["wp plugin list", "wp option get"])
    assert policy.check("run_wp_cli", "run_wp_cli → wp plugin list --path=/x") is True


def test_allowlist_does_not_approve_nonmatching():
    policy = ApprovalPolicy(approver=_deny, allow=["wp plugin list"])
    assert policy.check("run_wp_cli", "run_wp_cli → wp db reset --path=/x") is False


def test_allowlist_matches_plain_run_command():
    policy = ApprovalPolicy(approver=_deny, allow=["echo"])
    assert policy.check("run_command", "run_command → echo hi") is True


def test_empty_allowlist_still_prompts():
    policy = ApprovalPolicy(approver=_deny, allow=[])
    assert policy.check("run_command", "run_command → echo hi") is False


def test_mcp_call_is_gated():
    policy = ApprovalPolicy(approver=_deny)
    # gated -> approver says no -> not allowed
    assert policy.check("mcp__linear__create_issue",
                        "mcp__linear__create_issue → linear.create_issue({})") is False


def test_mcp_call_allowlist_by_namespaced_prefix():
    policy = ApprovalPolicy(approver=_deny, allow=("mcp__linear__",))
    assert policy.check("mcp__linear__create_issue",
                        "mcp__linear__create_issue → linear.create_issue({})") is True


def test_mcp_call_auto_approve():
    policy = ApprovalPolicy(auto_approve=True, approver=_deny)
    assert policy.check("mcp__x__y", "mcp__x__y → x.y({})") is True


def test_non_mcp_unknown_tool_still_ungated():
    policy = ApprovalPolicy(approver=_deny)
    assert policy.check("read_file", "read_file → /tmp/x") is True


def test_check_sampling_gated_declines():
    policy = ApprovalPolicy(approver=lambda n, d: "no")
    assert policy.check_sampling("srv", "preview text") is False


def test_check_sampling_allowlist_auto_approves():
    policy = ApprovalPolicy(approver=lambda n, d: "no", allow=("mcp_sample:srv",))
    assert policy.check_sampling("srv", "preview text") is True


def test_check_sampling_auto_approve():
    policy = ApprovalPolicy(auto_approve=True, approver=lambda n, d: "no")
    assert policy.check_sampling("srv", "preview text") is True


def test_check_label_prefixes_approver_detail():
    seen = {}
    def approver(name, detail):
        seen["name"] = name
        seen["detail"] = detail
        return "yes"
    policy = ApprovalPolicy(approver=approver)
    assert policy.check("write_file", "write_file → out.txt", label="researcher") is True
    assert seen["detail"] == "[researcher] write_file → out.txt"


def test_check_empty_label_leaves_detail_unchanged():
    seen = {}
    def approver(name, detail):
        seen["detail"] = detail
        return "yes"
    policy = ApprovalPolicy(approver=approver)
    policy.check("write_file", "write_file → out.txt")
    assert seen["detail"] == "write_file → out.txt"


def test_check_label_does_not_affect_allow_list_match():
    # The allow list keys on the command, not the label; a labeled call still
    # auto-approves without invoking the approver.
    def approver(name, detail):
        raise AssertionError("approver should not be called when allow-listed")
    policy = ApprovalPolicy(approver=approver, allow=("out.txt",))
    assert policy.check("write_file", "write_file → out.txt", label="researcher") is True


def test_check_serializes_concurrent_prompts():
    # The policy lock must ensure only one approver call runs at a time.
    active = 0
    max_active = 0
    guard = threading.Lock()

    def approver(name, detail):
        nonlocal active, max_active
        with guard:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.005)
        with guard:
            active -= 1
        return "yes"

    policy = ApprovalPolicy(approver=approver)
    threads = [
        threading.Thread(target=policy.check, args=("write_file", f"write_file → f{i}"))
        for i in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert max_active == 1  # serialized by the policy lock


def test_check_always_is_double_checked():
    calls = []

    def approver(name, detail):
        calls.append(name)
        return "always"

    policy = ApprovalPolicy(approver=approver)
    assert policy.check("write_file", "write_file → a") is True
    assert policy.check("write_file", "write_file → b") is True
    assert len(calls) == 1  # second call short-circuits on _always


def test_unified_file_diff_new_file(tmp_path):
    p = tmp_path / "x.txt"
    diff = unified_file_diff(p, "hello\n")
    assert "+hello" in diff


def test_unified_file_diff_existing_file(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("old line\n", encoding="utf-8")
    diff = unified_file_diff(p, "new line\n")
    assert "-old line" in diff
    assert "+new line" in diff


def test_unified_file_diff_no_change(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("same\n", encoding="utf-8")
    diff = unified_file_diff(p, "same\n")
    assert diff == ""


def test_confirm_true_when_auto_approve():
    pol = ApprovalPolicy(approver=lambda n, d: "no", auto_approve=True)
    assert pol.confirm("launch background agent") is True


def test_confirm_asks_the_approver_when_not_auto():
    asked = {}

    def approver(name, detail):
        asked["detail"] = detail
        return "yes"

    pol = ApprovalPolicy(approver=approver, auto_approve=False)
    assert pol.confirm("launch X", label="main") is True
    assert "launch X" in asked["detail"]


def test_confirm_false_on_no():
    pol = ApprovalPolicy(approver=lambda n, d: "no", auto_approve=False)
    assert pol.confirm("launch X") is False


def test_wp_tools_are_gated():
    from heya.approval import GATED_TOOLS
    assert "wp_run_ability" in GATED_TOOLS
    assert "wp_rest" in GATED_TOOLS
    assert "wp_abilities" not in GATED_TOOLS  # discovery is read-only and ungated
