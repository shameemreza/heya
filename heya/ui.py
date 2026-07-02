"""Terminal presentation layer.

A thin wrapper over rich that degrades to plain text when output is not a
terminal, when NO_COLOR is set, or when rich is unavailable. All terminal styling
lives here so the rest of the code stays plain. Nothing here crashes the REPL: a
render failure falls back to plain output."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path

try:
    from rich.console import Console
    _RICH = True
except Exception:  # rich missing or broken
    Console = None
    _RICH = False

try:
    from prompt_toolkit.completion import Completer, PathCompleter
    from prompt_toolkit.document import Document

    class _AtPathCompleter(Completer):
        """Complete filesystem paths for the fragment after the last '@'."""
        def __init__(self):
            self._paths = PathCompleter(expanduser=True)

        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            at = text.rfind("@")
            if at == -1:
                return
            frag = text[at + 1:]
            if " " in frag:
                return
            sub = Document(frag, len(frag))
            for c in self._paths.get_completions(sub, complete_event):
                yield c
except Exception:  # prompt_toolkit missing
    _AtPathCompleter = None

_WORDMARK = "Heya"  # a flat fallback; the rich path styles it

ART_GREEN = "#46B450"   # WordPress-family green for "HE"
ART_PURPLE = "#7F54B3"  # WooCommerce purple for "YA"

# Block-letter HEYA, split into a left "HE" half and a right "YA" half so each
# half can be styled independently (rich styles per segment, not per cell).
_HE_ROWS = [
    "█   █ █████",
    "█   █ █    ",
    "█████ ████ ",
    "█   █ █    ",
    "█   █ █████",
]
_YA_ROWS = [
    "█   █  ███ ",
    " █ █  █   █",
    "  █   █████",
    "  █   █   █",
    "  █   █   █",
]


def heya_art_rows() -> list[tuple[str, str]]:
    """Return the 5 art rows as (he_segment, ya_segment) pairs."""
    return list(zip(_HE_ROWS, _YA_ROWS))


def should_plain(out=None) -> bool:
    """Plain when there is no rich, NO_COLOR is set, or stdout is not a TTY."""
    if not _RICH:
        return True
    if os.environ.get("NO_COLOR"):
        return True
    out = out if out is not None else sys.stdout
    isatty = getattr(out, "isatty", None)
    return not (callable(isatty) and isatty())


class UI:
    def __init__(self, *, plain: bool = False, stream=None, write=None):
        self.plain = plain or not _RICH
        self.stream = stream  # input source for prompts; None -> interactive
        self._write = write or (lambda s: (sys.stdout.write(s), sys.stdout.flush()) and None)
        self.console = None
        if not self.plain:
            try:
                self.console = Console()
            except Exception:
                self.plain = True

    # --- output -------------------------------------------------------------
    def banner(self, *, version, model, profile, cwd, branch=""):
        tail = f" · {branch}" if branch else ""
        status = f"Heya v{version} · {model} · {profile} · {cwd}{tail}"
        if self.plain or self.console is None:
            self._write(f"{_WORDMARK} v{version}\n{model} · {profile} · {cwd}{tail}\n/help for commands\n\n")
            return
        try:
            self._render_art()
            self.console.print(status, style="dim")
            self.console.print("/help for commands\n", style="dim")
        except Exception:
            self._write(status + "\n")

    def _render_art(self) -> None:
        from rich.text import Text
        for he, ya in heya_art_rows():
            line = Text()
            line.append(he, style=f"bold {ART_GREEN}")
            line.append("  ")
            line.append(ya, style=f"bold {ART_PURPLE}")
            self.console.print(line)

    def stream_text(self, chunk: str):
        if self.plain or self.console is None:
            self._write(chunk)
            return
        try:
            self.console.print(chunk, end="", soft_wrap=True, highlight=False, markup=False)
        except Exception:
            self._write(chunk)

    def tool_event(self, summary: str):
        line = f"  · {summary}\n"
        if self.plain or self.console is None:
            self._write(line)
            return
        try:
            self.console.print(f"  · {summary}", style="dim")
        except Exception:
            self._write(line)

    def note(self, text: str):
        self._line(text, "dim")

    def error(self, text: str):
        self._line(text, "bold red")

    def _line(self, text, style):
        if self.plain or self.console is None:
            self._write(text + "\n")
            return
        try:
            self.console.print(text, style=style)
        except Exception:
            self._write(text + "\n")

    @contextmanager
    def status(self, label: str):
        if self.plain or self.console is None:
            yield
            return
        try:
            with self.console.status(label):
                yield
        except Exception:
            yield

    # --- input --------------------------------------------------------------
    def _prompt_session(self):
        if hasattr(self, "_pt"):
            return self._pt
        self._pt = None
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.history import FileHistory
            hist = Path.home() / ".config" / "heya" / "history"
            hist.parent.mkdir(parents=True, exist_ok=True)
            completer = _AtPathCompleter() if _AtPathCompleter is not None else None
            self._pt = PromptSession(history=FileHistory(str(hist)), completer=completer)
        except Exception:
            self._pt = None
        return self._pt

    def prompt(self, label: str = "you") -> str:
        if self.stream is not None:
            line = self.stream.readline()
            if line == "":
                raise EOFError
            return line
        if self.plain or self.console is None:
            return input(f"{label} > ")
        pt = self._prompt_session()
        if pt is not None:
            try:
                return pt.prompt(f"{label} > ")
            except EOFError:
                raise
            except Exception:
                pass
        try:
            from rich.prompt import Prompt
            return Prompt.ask(f"[bold green]{label} ›[/]", console=self.console)
        except Exception:
            return input(f"{label} > ")

    def approval(self, detail: str, *, diff: str | None = None) -> str:
        if diff:
            if self.plain or self.console is None:
                self._write(diff + "\n")
            else:
                self._render_diff(diff)
        if self.stream is not None:
            line = self.stream.readline()
            return line.strip().lower()[:1] or "n"
        return input(f"Allow {detail}? [y] once / [a] always / [n] no: ").strip().lower()[:1] or "n"

    def _render_diff(self, diff: str):
        try:
            from rich.text import Text
            t = Text()
            for ln in diff.splitlines():
                style = "green" if ln.startswith("+") else "red" if ln.startswith("-") else "dim"
                t.append(ln + "\n", style=style)
            self.console.print(t)
        except Exception:
            self._write(diff + "\n")
