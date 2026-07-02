from pathlib import Path
import pytest
from heya import tools
from heya.tools_files import read_file, ToolError

def test_read_file_permission_error_becomes_toolerror(tmp_path, monkeypatch):
    p = tmp_path / "f.txt"
    p.write_text("x")
    def boom(*a, **k):
        raise PermissionError("denied")
    monkeypatch.setattr(Path, "read_text", boom)
    with pytest.raises(ToolError):
        read_file(p, allowed_roots=[tmp_path])

def test_dispatch_wraps_oserror(monkeypatch, tmp_path):
    # write_file raising OSError must come back as an Error string, not raise
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr("heya.tools.write_file", boom)
    out = tools.dispatch_tool(
        "write_file", '{"path": "x.txt", "content": "y"}',
        allowed_roots=[tmp_path], cwd=tmp_path, timeout=5.0)
    assert out.startswith("Error:")
    assert "write_file" in out
