"""The ReAct agent loop: stream a reply, run approved tools, repeat.

One Agent instance holds the conversation, so interactive turns accumulate
context. Gated tools route through an ApprovalPolicy; results (including refusals
and errors) are always fed back so the model can recover. After a task that
changed something, one scoped self-review pass runs.
"""
from __future__ import annotations

import json
import math
import subprocess
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path
from typing import Any

from . import review
from .hooks import fire_hooks, hook_payload

from .agent_defs import agent_roles_note
from .approval import ApprovalPolicy, UiApprover, unified_file_diff
from .reproduction import (
    parse_issue_context, repro_workdir, gate_verdict, render_report, render_comment,
)
from .triage import gate_priority, render_triage_report, render_triage_comment, render_pick_list
from .diagnosis import (
    run_diagnosis, classify_log, extract_trace_frames,
    is_insufficient, escalation_should_stop,
)
from .remediation import (
    verify_remediation, check_fix_safety, gate_fix_verdict, render_solution,
    repair_should_stop,
)
from .context import build_summarizer, compact
from .memory import build_memory_block
from .skills import build_skills_block, render_skill
from .subagents import (
    LabeledStream, LockedSink, PARALLEL_SAFE_TOOLS, build_child_system_prompt,
    format_parallel_report, parallel_label, resolve_role, ROLES,
)
from .text import estimate_messages_tokens
from .tools import build_tool_schemas, describe_call, dispatch_tool
from .tools_files import resolve_in_allowlist

SYSTEM_PROMPT = (
    "You are Heya, a careful, capable command-line assistant. You help with "
    "engineering, support, research, writing, and analysis. You can read and write "
    "files and run shell commands, but only inside the folders you are allowed to "
    "use. Prefer reading before writing. Use tools to get real answers rather than "
    "guessing. Keep replies clear and direct, in natural human prose. When a task is "
    "done, give a short, plain final answer."
    " When a task involves writing, code review, debugging, or following standards, call read_guidance first to consult relevant internal guidance and follow it — it is the source of truth for standards and voice."
    " You can search the web (web_search) and read pages (web_fetch) when a task needs current or external information; note that these send the query or URL to a third party."
    " You can drive a real browser to reproduce issues: browser_navigate, browser_snapshot, browser_click, browser_type, browser_screenshot, and browser_evidence (console and network errors). Take a snapshot after each action to see the result."
    " For WordPress work you can tail a site's error log (read_log), run WP-CLI (run_wp_cli), and boot a disposable clean WordPress to reproduce on (wp_playground). Each takes the site's root directory as `path`; if you cannot tell which site is meant, ask the user rather than guessing. Use dev/staging sites only, never production, and back up before destructive WP-CLI ops (db reset, site empty)."
    " For long-lived commands (a dev server, a watcher), run_command with background=true returns a process id; read its output with check_command and stop it with kill_command."
    " You may also have MCP tools from servers the user configured (names like mcp__<server>__<tool>); these reach external systems and are approval-gated, and the user controls which servers are connected."
    " To work faster on independent read-only subtasks, spawn_agents runs several sub-agents in parallel — each read-only (research, review, analysis) — and returns all their reports at once for you to synthesize; use spawn_agent for a single task or anything that writes files or drives the browser."
)

SELF_REVIEW_NUDGE = (
    "Before finalizing: review what you just did against my original request. If "
    "anything is wrong, incomplete, or unsafe, fix it now with tools. If it is "
    "correct, reply with your final answer."
)

DEFAULT_MAX_ITERS = 12
DEFAULT_COMMAND_TIMEOUT = 120.0


class Agent:
    def __init__(
        self,
        client: Any,
        *,
        allowed_roots,
        cwd: Path,
        approval: ApprovalPolicy | None = None,
        on_text: Callable[[str], None] | None = None,
        self_review: bool = True,
        max_iters: int = DEFAULT_MAX_ITERS,
        command_timeout: float = DEFAULT_COMMAND_TIMEOUT,
        guidance_sources: Sequence[Path] = (),
        search_provider=None,
        browser_session=None,
        process_registry=None,
        wp_default_root=None,
        playground_session=None,
        mcp_runtime=None,
        label: str = "",
        spawn_depth: int = 0,
        max_spawn_depth: int = 1,
        max_children: int = 4,
        tool_filter: frozenset[str] | None = None,
        system_prompt: str = SYSTEM_PROMPT,
        max_concurrent: int = 4,
        root_on_text: Callable[[str], None] | None = None,
        on_tool: Callable[[str], None] | None = None,
        memory_store=None,
        skills=None,
        context_window: int = 32768,
        compaction_threshold: float = 0.85,
        reserve_tokens: int = 2048,
        keep_recent_tokens: int = 4096,
        task_token_budget: int = 200000,
        weak_client: Any = None,
        hooks=None,
        hooks_enabled=False,
        session_id="",
        agent_roles=None,
        identity=None,
    ) -> None:
        self.client = client
        self.weak_client = weak_client if weak_client is not None else client
        self.allowed_roots = list(allowed_roots)
        self.cwd = Path(cwd)
        self.approval = approval or ApprovalPolicy()
        self.on_text = on_text
        self.self_review = self_review
        self.max_iters = max_iters
        self.command_timeout = command_timeout
        self.guidance_sources = list(guidance_sources)
        self.search_provider = search_provider
        self.browser_session = browser_session
        self.process_registry = process_registry
        self.wp_default_root = wp_default_root
        self.playground_session = playground_session
        self.mcp_runtime = mcp_runtime
        self.label = label
        self.spawn_depth = spawn_depth
        self.max_spawn_depth = max_spawn_depth
        self.max_children = max_children
        self.tool_filter = tool_filter
        self.max_concurrent = max_concurrent
        self._on_tool = on_tool
        self._root_on_text = root_on_text if root_on_text is not None else on_text
        self._labeled_stream = None
        self._children_spawned = 0
        self.context_window = context_window
        self.compaction_threshold = compaction_threshold
        self.reserve_tokens = reserve_tokens
        self.keep_recent_tokens = keep_recent_tokens
        self.task_token_budget = task_token_budget
        self.session_tokens = 0
        self._task_tokens = 0
        self.weak_tokens = 0
        self._compaction_warned = False
        # Compaction summaries route through the weak model (with one-hop
        # fallback to main); see _weak_chat. Lazy so a client without chat()
        # never crashes at construction.
        self._summarize = build_summarizer(self._weak_chat)
        self.memory_store = memory_store
        system_content = system_prompt
        if memory_store is not None:
            system_content = system_content + "\n\n" + build_memory_block(memory_store.load_index())
        self.hooks = hooks or {}
        self.hooks_enabled = hooks_enabled
        self.session_id = session_id
        self.skills = skills or {}
        if self.skills:
            block = build_skills_block(self.skills)
            if block:
                system_content = system_content + "\n\n" + block
        self.agent_roles = agent_roles or {}
        if self.agent_roles:
            note = agent_roles_note(self.agent_roles)
            if note:
                system_content = system_content + "\n\n" + note
        self.identity = identity
        if self.identity is not None:
            from .config import build_identity_block
            line = build_identity_block(self.identity)
            if line:
                system_content = system_content + "\n\n" + line
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": system_content}]
        self._mutated = False

    def run(self, user_message: str) -> str:
        """Run one task to a final answer, with optional scoped self-review."""
        self._fire("SessionStart")
        self.messages.append({"role": "user", "content": user_message})
        self._fire("UserPromptSubmit")
        self._mutated = False
        self._children_spawned = 0  # per-task fan-out budget (spec: max_children per task)
        self._task_tokens = 0
        self._compaction_warned = False
        answer = self._loop()
        if self.self_review and self._mutated:
            self.messages.append({"role": "user", "content": SELF_REVIEW_NUDGE})
            self._mutated = False
            answer = self._loop()
        self._fire("Stop")
        return answer

    def close(self) -> None:
        """Release external resources: browser session, background processes,
        the WordPress Playground session, and the MCP runtime.

        For sub-agents (spawn_depth > 0), only close local output streams;
        shared resources are the parent's responsibility."""
        if self._labeled_stream is not None:
            self._labeled_stream.close()
        if self.spawn_depth == 0:
            # Only the root agent closes shared resources
            if self.browser_session is not None:
                self.browser_session.close()
            if self.process_registry is not None:
                self.process_registry.close()
            if self.playground_session is not None:
                self.playground_session.close()
            if self.mcp_runtime is not None:
                self.mcp_runtime.close()

    def _loop(self) -> str:
        can_spawn = self.spawn_depth < self.max_spawn_depth
        with_memory = self.memory_store is not None
        tools = build_tool_schemas(self.mcp_runtime, can_spawn=can_spawn, with_memory=with_memory, with_review=can_spawn, with_repro=can_spawn, with_diagnose=can_spawn, with_remediate=can_spawn, with_skills=bool(self.skills), with_triage=can_spawn)
        if self.tool_filter is not None:
            tools = [t for t in tools if t["function"]["name"] in self.tool_filter]
        for _ in range(self.max_iters):
            self._maybe_compact()
            if self.task_token_budget and self._task_tokens >= self.task_token_budget:
                return f"Stopped: reached this task's token budget ({self._task_tokens} tokens)."
            result = self.client.chat_stream(self.messages, tools=tools, on_text=self.on_text)
            self._account(result)
            self.messages.append(self._assistant_message(result))
            if not result.tool_calls:
                return result.content or ""
            for call in result.tool_calls:
                output = self._handle_call(call)
                self.messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": output}
                )
        return "Stopped: reached max iterations without a final answer."

    def _maybe_compact(self) -> None:
        trigger = self.context_window * self.compaction_threshold - self.reserve_tokens
        before = estimate_messages_tokens(self.messages)
        if before < trigger:
            return
        self.messages = compact(
            self.messages, context_window=self.context_window,
            threshold=self.compaction_threshold, reserve_tokens=self.reserve_tokens,
            keep_recent_tokens=self.keep_recent_tokens, summarize_fn=self._summarize,
        )
        after = estimate_messages_tokens(self.messages)
        if after >= before * 0.9 and not self._compaction_warned:
            self._compaction_warned = True
            if self._root_on_text is not None:
                self._root_on_text("\n[context near full; could not reduce further]\n")

    def _account(self, result) -> None:
        tokens = result.usage.total_tokens if getattr(result, "usage", None) else 0
        self._task_tokens += tokens
        self.session_tokens += tokens

    def _weak_chat(self, messages):
        """Run one chat() call on the weak model, falling back once to the main
        model on any failure. Weak tokens bucket into self.weak_tokens; tokens
        that actually ran on the main client bucket into self.session_tokens.
        Neither path touches self._task_tokens — the per-task budget stays in
        main-model tokens."""
        if self.weak_client is self.client:
            result = self.client.chat(messages)
            self.session_tokens += self._usage_tokens(result)
            return result
        try:
            result = self.weak_client.chat(messages)
        except Exception:
            if self._root_on_text is not None:
                self._root_on_text("\n[weak model unavailable; using main model]\n")
            result = self.client.chat(messages)  # may raise; compact() handles
            self.session_tokens += self._usage_tokens(result)
            return result
        self.weak_tokens += self._usage_tokens(result)
        return result

    @staticmethod
    def _usage_tokens(result) -> int:
        return result.usage.total_tokens if getattr(result, "usage", None) else 0

    def _assistant_message(self, result) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "assistant", "content": result.content or ""}
        if result.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
                for call in result.tool_calls
            ]
        return message

    def _run_hook_command(self, spec, *, stdin):
        """Run one command hook's process: stdin = the JSON payload; returns
        (exit_code, stdout, stderr). Confined to the allowlist cwd; a timeout is a
        non-blocking error (exit 1)."""
        argv = [spec.command, *spec.args]
        shell = len(spec.args) == 0  # shell form when no explicit args (Claude's rule)
        try:
            cwd = resolve_in_allowlist(self.cwd, self.allowed_roots)
            proc = subprocess.run(
                spec.command if shell else argv, shell=shell, cwd=str(cwd),
                input=stdin, capture_output=True, text=True, timeout=spec.timeout,
            )
            return (proc.returncode, proc.stdout, proc.stderr)
        except subprocess.TimeoutExpired:
            return (1, "", f"hook timed out after {spec.timeout}s")

    def _fire(self, event, *, tool_name=None, tool_input=None, tool_output=None):
        if not self.hooks_enabled:
            return None
        payload = hook_payload(event, session_id=self.session_id, cwd=str(self.cwd),
                               tool_name=tool_name, tool_input=tool_input, tool_output=tool_output)
        return fire_hooks(event, self.hooks, payload, enabled=self.hooks_enabled,
                          runner=self._run_hook_command, tool_name=tool_name,
                          on_note=self._root_on_text)

    def _handle_call(self, call) -> str:
        detail = describe_call(call.name, call.arguments)
        if self.tool_filter is not None and call.name not in self.tool_filter:
            return f"Error: tool {call.name!r} is not available to the {self.label} sub-agent."
        if call.name == "write_file" and isinstance(
            getattr(self.approval, "_approver", None), UiApprover
        ):
            try:
                args = json.loads(call.arguments) if call.arguments.strip() else {}
                path = args.get("path", "")
                resolve_in_allowlist(path, self.allowed_roots)  # raises if outside
                diff = unified_file_diff(path, args.get("content", ""))
                self.approval._approver.set_diff(diff or None)
            except Exception:
                pass
        if not self.approval.check(call.name, detail, label=self.label):
            return f"Declined by user: {detail}"
        pre = self._fire("PreToolUse", tool_name=call.name, tool_input=call.arguments)
        if pre is not None and pre.block:
            return f"Blocked by PreToolUse hook: {pre.message or '(no reason given)'}"
        if self._on_tool is not None:
            label = f"[{self.label}] " if self.label else ""
            try:
                self._on_tool(label + detail)
            except Exception:
                pass  # the trace is best-effort
        output = dispatch_tool(
            call.name,
            call.arguments,
            allowed_roots=self.allowed_roots,
            cwd=self.cwd,
            timeout=self.command_timeout,
            guidance_sources=self.guidance_sources,
            search_provider=self.search_provider,
            browser_session=self.browser_session,
            process_registry=self.process_registry,
            wp_default_root=self.wp_default_root,
            playground_session=self.playground_session,
            mcp_runtime=self.mcp_runtime,
            spawn_fn=self._spawn_agent,
            spawn_agents_fn=self._spawn_agents,
            memory_store=self.memory_store,
            review_fn=self._review_changes,
            start_repro_fn=self._start_reproduction,
            repro_verdict_fn=self._record_repro_verdict,
            diagnose_fn=self._diagnose_issue,
            check_remediation_fn=self._check_remediation,
            fix_verdict_fn=self._record_fix_verdict,
            skill_fn=self._skill,
            triage_report_fn=self._triage_report,
            pick_list_fn=self._record_pick_list,
        )
        self._fire("PostToolUse", tool_name=call.name, tool_input=call.arguments, tool_output=output)
        mutating = call.name in ("write_file", "run_command", "run_wp_cli")
        if mutating and not output.startswith(("Error", "Started background process", "Declined")):
            self._mutated = True
        return output

    def _make_child(self, role, instructions, *, parallel=False, index=0, sink=None, weak=False) -> "Agent":
        """Build a fresh child Agent: isolated context, shared resources.

        parallel=True builds a READ-ONLY child for concurrent fan-out: the single
        stateful sessions are withheld, tools are the read-only surface, the label
        is indexed, and output routes through the shared locked `sink`."""
        if parallel:
            label = parallel_label(role.name if role is not None else None, index)
            base_sink = sink if sink is not None else self._root_on_text
            role_tools = role.tools if role is not None else None
            tool_filter = PARALLEL_SAFE_TOOLS if role_tools is None else (role_tools & PARALLEL_SAFE_TOOLS)
            browser = process = playground = None
        else:
            label = role.name if role is not None else "agent"
            if weak:
                label = f"{label}·weak"
            base_sink = self._root_on_text
            tool_filter = role.tools if role is not None else None
            browser = self.browser_session
            process = self.process_registry
            playground = self.playground_session
        stream = None
        if base_sink is not None:
            stream = LabeledStream(base_sink, label)
            child_on_text = stream.write
        else:
            child_on_text = None
        child_client = self.weak_client if weak else self.client
        child = Agent(
            child_client,
            allowed_roots=self.allowed_roots,
            cwd=self.cwd,
            approval=self.approval,
            on_text=child_on_text,
            self_review=False,
            max_iters=self.max_iters,
            command_timeout=self.command_timeout,
            guidance_sources=self.guidance_sources,
            search_provider=self.search_provider,
            browser_session=browser,
            process_registry=process,
            wp_default_root=self.wp_default_root,
            playground_session=playground,
            mcp_runtime=self.mcp_runtime,
            label=label,
            spawn_depth=self.spawn_depth + 1,
            max_spawn_depth=self.max_spawn_depth,
            max_children=self.max_children,
            tool_filter=tool_filter,
            system_prompt=build_child_system_prompt(SYSTEM_PROMPT, role, instructions),
            max_concurrent=self.max_concurrent,
            root_on_text=self._root_on_text,
            context_window=self.context_window,
            compaction_threshold=self.compaction_threshold,
            reserve_tokens=self.reserve_tokens,
            keep_recent_tokens=self.keep_recent_tokens,
            task_token_budget=self.task_token_budget,
            weak_client=self.weak_client,
            skills=self.skills,
            hooks=self.hooks,
            hooks_enabled=self.hooks_enabled,
            session_id=self.session_id,
            agent_roles=self.agent_roles,
            identity=self.identity,
            on_tool=self._on_tool,
        )
        child._labeled_stream = stream
        return child

    def _spawn_agent(self, task, role=None, instructions=None, weak=False) -> str:
        """Run a child agent to completion and return its final report."""
        if self._children_spawned >= self.max_children:
            return "Error: sub-agent limit reached for this task."
        resolved = resolve_role(role) or (self.agent_roles.get(role) if role else None)
        if role is not None and resolved is None:
            available = sorted(set(ROLES) | set(self.agent_roles))
            return f"Error: unknown role {role!r}. Available: {available}."
        self._children_spawned += 1
        child = self._make_child(resolved, instructions, weak=weak)
        try:
            return child.run(task)
        except Exception as exc:  # never raise into dispatch
            return f"Error: sub-agent failed: {exc}"
        finally:
            child.close()

    def _spawn_agents(self, tasks) -> str:
        """Run several READ-ONLY children concurrently; return their submission-ordered
        reports. Per-child error isolation + a wall-clock timeout; never raises."""
        try:
            return self._run_parallel(tasks)
        except Exception as exc:  # never raise into dispatch
            return f"Error: spawn_agents failed: {exc}"

    def _run_children(self, specs) -> list[tuple[str, str]]:
        """Run read-only parallel children for `specs`; return [(label, report)] in
        submission order. specs: dicts with 'prompt' (required), 'role', 'instructions',
        'label'. Budget-free — the caller bounds the count. Per-child error isolation
        and a wall-clock deadline scaled by the number of waves."""
        if not specs:
            return []
        locked = LockedSink(self._root_on_text) if self._root_on_text is not None else None
        results: list = [None] * len(specs)

        def work(i, spec):
            child = None
            try:
                child = self._make_child(
                    spec.get("role"), spec.get("instructions"),
                    parallel=True, index=i + 1,
                    sink=locked.write if locked is not None else None,
                )
                return child.run(spec["prompt"])
            except Exception as exc:
                return f"Error: sub-agent failed: {exc}"
            finally:
                if child is not None:
                    child.close()

        max_workers = max(1, min(len(specs), self.max_concurrent))
        waves = math.ceil(len(specs) / max_workers)
        deadline = self.command_timeout * 1.5 * waves
        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            futures = {executor.submit(work, i, spec): i for i, spec in enumerate(specs)}
            try:
                for fut in as_completed(futures, timeout=deadline):
                    results[futures[fut]] = fut.result()
            except FuturesTimeout:
                pass
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        out = []
        for i, spec in enumerate(specs):
            role = spec.get("role")
            label = spec.get("label") or parallel_label(
                role.name if role is not None else None, i + 1)
            out.append((label, results[i]))
        return out

    def _run_parallel(self, tasks) -> str:
        if not isinstance(tasks, list) or not tasks:
            return "Error: spawn_agents requires a non-empty list of tasks."
        specs = []  # (task, resolved_role_or_None, instructions)
        for t in tasks:
            if not isinstance(t, dict) or not t.get("task"):
                return "Error: each spawn_agents task needs a 'task' string."
            role_name = t.get("role")
            resolved = resolve_role(role_name) or (self.agent_roles.get(role_name) if role_name else None)
            if role_name is not None and resolved is None:
                return f"Error: unknown role {role_name!r}. Available: {sorted(set(ROLES) | set(self.agent_roles))}."
            specs.append((t["task"], resolved, t.get("instructions")))
        remaining = self.max_children - self._children_spawned
        if remaining <= 0:
            return "Error: sub-agent limit reached for this task."
        dropped = max(0, len(specs) - remaining)
        run = specs[:remaining]
        self._children_spawned += len(run)
        children_specs = [{"prompt": task, "role": role, "instructions": instr}
                          for (task, role, instr) in run]
        children = self._run_children(children_specs)

        parts = []
        for i, (task, role, _instr) in enumerate(run):
            label, res = children[i]
            if res is None:
                parts.append(format_parallel_report(
                    label, task, "(no result before timeout)", status="timed-out"))
            elif isinstance(res, str) and res.startswith("Error: sub-agent failed"):
                parts.append(format_parallel_report(label, task, res, status="failed"))
            else:
                parts.append(format_parallel_report(label, task, res, status="ok"))
        out = "\n\n".join(parts)
        if dropped:
            out += (f"\n\n(Note: {dropped} task(s) not run — per-task sub-agent "
                    f"budget is {self.max_children}.)")
        return out

    REVIEW_REVIEWERS = [
        ("code-reviewer", "correctness and quality", "code-review", ""),
        ("security-reviewer", "security", "wp-security", review.WP_SECURITY_METHODOLOGY),
        ("standards-reviewer", "standards", "woocommerce-code-review", review.WP_STANDARDS_METHODOLOGY),
    ]

    def _review_panel(self, focus):
        """The reviewer subset for a focus: 'all' → the whole panel; a dimension
        keyword → just that reviewer; an unknown focus → the whole panel."""
        focus = (focus or "all").strip().lower()
        if focus == "all":
            return self.REVIEW_REVIEWERS
        matched = [r for r in self.REVIEW_REVIEWERS
                   if focus in r[1].lower() or focus in r[0].lower()]
        return matched or self.REVIEW_REVIEWERS

    def _review_changes(self, target="branch", focus="all") -> str:
        """Run the deterministic review pipeline; never raises into dispatch."""
        def runner(argv, cwd):
            # Run git as an arg LIST (no shell) so a path with metacharacters can't
            # inject; `cwd` is already allow-list-confined by git_diff.
            import subprocess
            try:
                proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                                      timeout=self.command_timeout)
            except (subprocess.TimeoutExpired, OSError) as exc:
                return (1, "", str(exc))
            return (proc.returncode, proc.stdout, proc.stderr)
        try:
            return review.run_review(
                target or "branch",
                run_children=self._run_children,
                git_diff_fn=lambda t: review.git_diff(
                    t, allowed_roots=self.allowed_roots, cwd=self.cwd, runner=runner),
                reviewers=self._review_panel(focus),
                standards=(self.memory_store.load_index() if self.memory_store else ""),
            )
        except Exception as exc:  # never raise into dispatch
            return f"Error: review failed: {exc}"

    def _start_reproduction(self, **fields) -> str:
        try:
            ctx = parse_issue_context(fields)
            if ctx.missing:
                return (
                    "blocked: needs-info. Missing required fields: "
                    + ", ".join(ctx.missing)
                    + ". No environment was built. Ask the reporter for these, "
                    "then call start_reproduction again."
                )
            slug = fields.get("slug") or ctx.source or "issue"
            base = repro_workdir(slug, allowed_roots=self.allowed_roots, cwd=self.cwd)
            (base / "repro-spec.json").write_text(json.dumps(ctx.to_dict(), indent=2))
            return (
                f"Working folder ready: {base}\n"
                f"Spec written to repro-spec.json. Now run the funnel "
                f"(read_guidance('reproduction')): update -> theme test -> plugin "
                f"test -> clean Playground repro. Code-level checks before the "
                f"browser. Save artifacts under {base / 'evidence'}. End with "
                f"record_repro_verdict."
            )
        except Exception as exc:  # never raise into dispatch
            return f"Error: start_reproduction failed: {exc}"

    def _skill(self, name, arguments="") -> str:
        item = self.skills.get(name)
        if item is None:
            available = ", ".join(sorted(self.skills)) or "(none)"
            return f"Error: unknown skill {name!r}. Available: {available}"
        try:
            return render_skill(item, arguments)
        except Exception as exc:  # never raise into dispatch
            return f"Error: skill {name!r} failed to load: {exc}"

    def _diagnose_issue(self, **fields) -> str:
        try:
            slug = fields.get("slug") or "issue"
            evidence = fields.get("evidence", "")
            logs = fields.get("logs", "")
            base = repro_workdir(slug, allowed_roots=self.allowed_roots, cwd=self.cwd)
            spec_path = base / "repro-spec.json"
            ctx = parse_issue_context(
                json.loads(spec_path.read_text()) if spec_path.is_file() else {"source": slug}
            )
            # Seed deterministic signals into the context handed to the explorers.
            seeds = []
            log_hits = classify_log(logs)
            if log_hits:
                seeds.append("log patterns: " + ", ".join(f"{p} -> {c}" for p, c in log_hits))
            frames = extract_trace_frames(logs)
            if frames:
                seeds.append("trace frames: " + ", ".join(f"{f}:{n}" for f, n in frames))
            context = (
                f"source: {ctx.source}\nsteps: {', '.join(ctx.steps)}\n"
                f"expected: {ctx.expected}\nactual: {ctx.actual}\n"
                + ("\n".join(seeds))
            )
            result = run_diagnosis(context, evidence, run_children=self._run_children)
            (base / "diagnosis.md").write_text(result)
            # Bounded escalation loop: when diagnosis cannot localize, tell the agent
            # to gather one more signal and retry, capped in code via a durable counter.
            rounds_path = base / "diagnosis-rounds.json"
            rounds = 0
            if rounds_path.is_file():
                try:
                    rounds = int(json.loads(rounds_path.read_text()))
                except (ValueError, TypeError):
                    rounds = 0
            note = ""
            if is_insufficient(result):
                rounds += 1
                rounds_path.write_text(json.dumps(rounds))
                stop, reason = escalation_should_stop(rounds, cap=2)
                if stop:
                    note = (
                        f"\n\nblocked: insufficient evidence after {rounds} rounds "
                        f"({reason}). Report it honestly with what you tried and what is "
                        f"still missing; do not guess a cause."
                    )
                else:
                    note = (
                        f"\n\nEscalation round {rounds}: not localized yet. Gather ONE "
                        f"more signal (enable WP_DEBUG_LOG and re-read the log; run a wp "
                        f"diagnostic you have not run; widen or repeat the conflict test), "
                        f"then call diagnose_issue again."
                    )
            else:
                rounds_path.write_text(json.dumps(0))  # grounded result resets the loop
            return f"Diagnosis written to {base / 'diagnosis.md'}.{note}\n\n{result}"
        except Exception as exc:  # never raise into dispatch
            return f"Error: diagnose_issue failed: {exc}"

    def _check_remediation(self, **fields) -> str:
        try:
            slug = fields.get("slug") or "issue"
            kind = fields.get("kind", "")
            content = fields.get("content", "")
            base = repro_workdir(slug, allowed_roots=self.allowed_roots, cwd=self.cwd)
            spec_path = base / "repro-spec.json"
            ctx = parse_issue_context(
                json.loads(spec_path.read_text()) if spec_path.is_file() else {"source": slug}
            )
            diag_path = base / "diagnosis.md"
            diag = diag_path.read_text() if diag_path.is_file() else ""
            context = (
                f"source: {ctx.source}\nexpected: {ctx.expected}\nactual: {ctx.actual}\n"
                + (f"diagnosis:\n{diag}" if diag else "")
            )
            grounding = verify_remediation(content, context, run_children=self._run_children)
            safe, safe_msg = check_fix_safety(kind, content)
            safety = ("edit-safety: ok - " + safe_msg) if safe else ("edit-safety: FAILED - " + safe_msg)
            return f"{grounding}\n\n{safety}"
        except Exception as exc:  # never raise into dispatch
            return f"Error: check_remediation failed: {exc}"

    def _record_fix_verdict(self, **fields) -> str:
        try:
            slug = fields.get("slug") or "issue"
            evidence = list(fields.get("evidence") or [])
            content = fields.get("content", "")
            verdict = gate_fix_verdict(
                repro_passes=bool(fields.get("repro_passes")),
                regression_passes=bool(fields.get("regression_passes")),
                evidence=evidence,
            )
            base = repro_workdir(slug, allowed_roots=self.allowed_roots, cwd=self.cwd)
            # Durable attempt log bounds the agent's repair loop (in code, not just
            # the prompt). Load prior attempts, decide stop BEFORE appending this one.
            log_path = base / "attempts.json"
            attempts = []
            if log_path.is_file():
                try:
                    attempts = json.loads(log_path.read_text())
                except ValueError:
                    attempts = []
            loop_note = ""
            if verdict == "verified":
                attempts.append({"patch": content, "signature": "verified", "verified": True})
            else:
                stop, reason = repair_should_stop(attempts, content, cap=3)
                signature = " ".join(sorted(evidence))[:200]
                attempts.append({"patch": content, "signature": signature, "verified": False})
                loop_note = (
                    f" Not verified (attempt {len(attempts)}). "
                    + (f"STOP refining and report the best attempt: {reason}." if stop
                       else "You may refine once more and retry, feeding back the raw failure.")
                )
            log_path.write_text(json.dumps(attempts, indent=2))
            spec_path = base / "repro-spec.json"
            ctx = parse_issue_context(
                json.loads(spec_path.read_text()) if spec_path.is_file() else {"source": slug}
            )
            solution = render_solution(
                ctx, kind=fields.get("kind", ""), content=content,
                verdict=verdict, evidence=evidence,
                how_to_apply=fields.get("how_to_apply", ""), caveats=fields.get("caveats", ""),
            )
            (base / "solution.md").write_text(solution)
            return (f"Fix verdict: {verdict}.{loop_note} Wrote {base / 'solution.md'}. "
                    f"Not posted anywhere; share or apply it yourself.")
        except Exception as exc:  # never raise into dispatch
            return f"Error: record_fix_verdict failed: {exc}"

    def _triage_report(self, **fields) -> str:
        try:
            slug = fields.get("slug") or "issue"
            base = repro_workdir(slug, allowed_roots=self.allowed_roots, cwd=self.cwd)
            spec_path = base / "repro-spec.json"
            ctx = parse_issue_context(
                json.loads(spec_path.read_text()) if spec_path.is_file() else {"source": slug}
            )
            diag = (base / "diagnosis.md").read_text() if (base / "diagnosis.md").is_file() else ""
            sol = (base / "solution.md").read_text() if (base / "solution.md").is_file() else ""
            verdict = fields.get("verdict", "")
            priority = gate_priority(fields.get("priority", ""), verdict)
            evidence = list(fields.get("evidence") or [])
            pairs = [tuple(vr) for vr in (fields.get("version_results") or []) if len(tuple(vr)) == 2]
            common = dict(verdict=verdict, what_happens=fields.get("what_happens", ""),
                          impact=fields.get("impact", ""), priority=priority, evidence=evidence,
                          repro_link=fields.get("repro_link", ""), next_step=fields.get("next_step", ""))
            report = render_triage_report(
                ctx, candidate_area=fields.get("candidate_area", ""), version_results=pairs,
                diagnosis_summary=diag[:1500], solution_summary=sol[:1500], **common)
            comment = render_triage_comment(ctx, **common)
            (base / "triage-report.md").write_text(report)
            (base / "triage-comment.md").write_text(comment)
            return (f"Triage report ready (priority: {priority}). Wrote {base / 'triage-report.md'} "
                    f"and {base / 'triage-comment.md'}. Paste the comment yourself; not posted anywhere.")
        except Exception as exc:  # never raise into dispatch
            return f"Error: triage_report failed: {exc}"

    def _record_pick_list(self, **fields) -> str:
        try:
            source = fields.get("source", "backlog")
            items = fields.get("items") or []
            out = render_pick_list(source, items)
            target = resolve_in_allowlist(Path(self.cwd) / "pick-list.md", self.allowed_roots)
            target.write_text(out)
            return f"Pick-list written to {target}. Not posted anywhere.\n\n{out}"
        except Exception as exc:  # never raise into dispatch
            return f"Error: record_pick_list failed: {exc}"

    def _record_repro_verdict(self, **fields) -> str:
        # **fields (not explicit kwargs) so an unexpected key from the model can
        # never raise a bind-time TypeError outside this try/except.
        try:
            slug = fields.get("slug") or "issue"
            verdict = fields.get("verdict") or "blocked"
            evidence = list(fields.get("evidence") or [])
            what_happens = fields.get("what_happens", "")
            summary = fields.get("summary", "")
            suggested_next_step = fields.get("suggested_next_step", "")
            pairs = [tuple(vr) for vr in (fields.get("version_results") or []) if len(tuple(vr)) == 2]
            final = gate_verdict(verdict, evidence)
            base = repro_workdir(slug, allowed_roots=self.allowed_roots, cwd=self.cwd)
            # Re-parse a minimal context for rendering from the saved spec when present.
            spec_path = base / "repro-spec.json"
            ctx = parse_issue_context(
                json.loads(spec_path.read_text()) if spec_path.is_file() else {"source": slug}
            )
            report = render_report(ctx, final, evidence, what_happens, summary, pairs, suggested_next_step)
            comment = render_comment(ctx, final, evidence, what_happens, summary, pairs, suggested_next_step)
            (base / "report.md").write_text(report)
            (base / "comment.md").write_text(comment)
            note = ""
            if final != verdict:
                note = (
                    f" (verdict downgraded from '{verdict}' to '{final}': no evidence "
                    f"was provided)"
                )
            return (
                f"Verdict: {final}{note}. Wrote {base / 'report.md'} and "
                f"{base / 'comment.md'}. Not posted anywhere; share or post them yourself."
            )
        except Exception as exc:  # never raise into dispatch
            return f"Error: record_repro_verdict failed: {exc}"
