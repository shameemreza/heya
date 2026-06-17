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
