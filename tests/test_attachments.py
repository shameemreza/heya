from heya import attachments


def test_parse_mentions():
    assert attachments.parse_mentions("look at @a.log and @img.png please") == ["a.log", "img.png"]
    assert attachments.parse_mentions("no mentions here") == []
    assert attachments.parse_mentions("email me@x.com is not a mention") == []


def test_no_mentions_returns_plain_string(tmp_path):
    content, info = attachments.build_user_content("hello", allowed_roots=[tmp_path], cwd=tmp_path)
    assert content == "hello" and info["has_image"] is False


def test_text_file_inlined(tmp_path):
    f = tmp_path / "error.log"
    f.write_text("fatal: boom")
    content, info = attachments.build_user_content(
        "explain @error.log", allowed_roots=[tmp_path], cwd=tmp_path)
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "explain @error.log"}
    assert any(b.get("type") == "text" and "fatal: boom" in b["text"] for b in content[1:])
    assert info["has_image"] is False


def test_image_becomes_base64_block(tmp_path):
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
    content, info = attachments.build_user_content(
        "see @shot.png", allowed_roots=[tmp_path], cwd=tmp_path)
    block = [b for b in content if b.get("type") == "image_url"][0]
    assert block["image_url"]["url"].startswith("data:image/png;base64,")
    assert info["has_image"] is True


def test_out_of_allowlist_is_a_note(tmp_path):
    content, info = attachments.build_user_content(
        "see @/etc/passwd", allowed_roots=[tmp_path], cwd=tmp_path)
    assert content == "see @/etc/passwd"  # nothing readable -> plain string
    assert any("could not include" in n for n in info["notes"])


def test_size_cap_truncates(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("A" * (300 * 1024))
    content, info = attachments.build_user_content(
        "@big.txt", allowed_roots=[tmp_path], cwd=tmp_path)
    text_block = [b for b in content if b.get("type") == "text" and "Contents of" in b["text"]][0]
    assert "truncated" in text_block["text"]
