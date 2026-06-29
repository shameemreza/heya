from heya.tools_guidance import (
    BUNDLED_GUIDANCE_DIR,
    _frontmatter,
    collect_guidance,
    read_guidance,
)

# Every WordPress guidance file, in router order.
WP_FILES = [
    "wordpress",
    "wp-security",
    "wp-plugin-structure",
    "wp-standards-i18n",
    "wp-readme-naming",
    "wp-themes",
    "wp-blocks",
    "wc-extension",
]

# The seven deep-dive files the router entry must point at.
WP_DEEP_DIVES = [f for f in WP_FILES if f != "wordpress"]


def _read(name):
    return read_guidance(name, sources=[BUNDLED_GUIDANCE_DIR])


def _has_valid_frontmatter(name):
    fm = _frontmatter(_read(name))
    return fm.get("name") == name and bool(fm.get("description"))


def test_wordpress_entry_loads_with_frontmatter():
    text = _read("wordpress")
    assert text.strip()
    assert _has_valid_frontmatter("wordpress")


def test_wordpress_entry_routes_to_every_deep_dive():
    text = _read("wordpress")
    for name in WP_DEEP_DIVES:
        assert name in text, f"wordpress.md does not route to {name}"


def test_wordpress_entry_carries_the_essentials():
    text = _read("wordpress")
    for token in ["ABSPATH", "current_user_can", "$wpdb->prepare", "Plugin Check"]:
        assert token in text, f"wordpress.md is missing essential: {token}"
