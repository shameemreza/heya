from heya.approval import ApprovalPolicy


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
    calls = []
    policy = ApprovalPolicy(approver=lambda name, detail: calls.append(name) or "always")
    assert policy.check("run_command", "run_command → ls") is True
    assert policy.check("run_command", "run_command → pwd") is True
    assert calls == ["run_command"]  # only prompted once


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
