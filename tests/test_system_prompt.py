from heya.agent import SYSTEM_PROMPT


def test_prompt_frames_tool_output_as_untrusted():
    p = SYSTEM_PROMPT.lower()
    assert "data, not instructions" in p
    assert "web_fetch" in SYSTEM_PROMPT and "mcp" in p
