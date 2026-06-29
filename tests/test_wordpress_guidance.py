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


def test_wp_security_loads_with_frontmatter():
    assert _read("wp-security").strip()
    assert _has_valid_frontmatter("wp-security")


def test_wp_security_covers_core_rules():
    text = _read("wp-security")
    required = [
        "esc_html",
        "esc_url",
        "wp_kses_post",
        "wp_unslash",
        "sanitize_text_field",
        "current_user_can",
        "$wpdb->prepare",
        "wp_handle_upload",
        "wp_safe_remote",
        "wp_privacy_personal_data_exporters",
    ]
    for token in required:
        assert token in text, f"wp-security.md is missing: {token}"


def test_wp_security_names_forbidden_functions():
    text = _read("wp-security")
    for token in ["eval", "unserialize"]:
        assert token in text, f"wp-security.md should warn about: {token}"


def test_wp_plugin_structure_loads_with_frontmatter():
    assert _read("wp-plugin-structure").strip()
    assert _has_valid_frontmatter("wp-plugin-structure")


def test_wp_plugin_structure_covers_core_rules():
    text = _read("wp-plugin-structure")
    required = [
        "ABSPATH",
        "WP_UNINSTALL_PLUGIN",
        "wp_enqueue_script",
        "plugin_dir_path",
        "register_activation_hook",
        "register_setting",
        "permission_callback",
        "admin_notices",
    ]
    for token in required:
        assert token in text, f"wp-plugin-structure.md is missing: {token}"


def test_wp_standards_i18n_loads_with_frontmatter():
    assert _read("wp-standards-i18n").strip()
    assert _has_valid_frontmatter("wp-standards-i18n")


def test_wp_standards_i18n_covers_core_rules():
    text = _read("wp-standards-i18n")
    required = ["Yoda", "Text Domain", "translators:", "_n("]
    for token in required:
        assert token in text, f"wp-standards-i18n.md is missing: {token}"
    assert "init" in text


def test_wp_readme_naming_loads_with_frontmatter():
    assert _read("wp-readme-naming").strip()
    assert _has_valid_frontmatter("wp-readme-naming")


def test_wp_readme_naming_covers_core_rules():
    text = _read("wp-readme-naming")
    required = [
        "Stable tag",
        "Requires PHP",
        "Tested up to",
        "GPL",
        "for WooCommerce",
        "trademark",
    ]
    for token in required:
        assert token in text, f"wp-readme-naming.md is missing: {token}"
