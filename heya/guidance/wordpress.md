---
name: wordpress
description: Entry point for WordPress work. The must-follow rules for a secure, compliant plugin, theme, or snippet, a before-you-submit checklist, and a router to the deeper WordPress guidance.
---

# WordPress development

Read this file first for any WordPress plugin, theme, or code snippet. Follow
it in full. The deep-dive files this file routes to carry the detail; this file
carries the rules that nothing overrides.

## The non-negotiables

These apply to every file you write or change. There are no exceptions.

**Guard every PHP file against direct access.**

```php
defined( 'ABSPATH' ) || exit;
```

Put this at the top of every PHP file.

**Sanitize every input at the point you receive it.**

Use the most specific sanitizer available: `sanitize_text_field`, `absint`,
`sanitize_email`, `wp_kses_post`. Never pass raw `$_GET`, `$_POST`, or
`$_REQUEST` data directly to any function.

**Escape every output at the point you output it.**

Escape late, escape contextually. Use `esc_html`, `esc_attr`, `esc_url`,
`esc_js`, or `wp_kses_post` to match the output context. Never escape early and
store the escaped value.

**Verify a nonce and check a capability on every state change.**

```php
check_admin_referer( 'my_action_nonce' );
if ( ! current_user_can( 'manage_options' ) ) {
    wp_die( esc_html__( 'You do not have permission.', 'my-plugin' ) );
}
```

A nonce without a capability check is incomplete. A capability check without a
nonce is incomplete. Both are required on every form submission, AJAX handler,
and REST endpoint that modifies data.

**Use `$wpdb->prepare()` for any query with variable data.**

```php
$results = $wpdb->get_results(
    $wpdb->prepare(
        'SELECT * FROM %i WHERE user_id = %d',
        $wpdb->prefix . 'my_table',
        absint( $user_id )
    )
);
```

Never interpolate variables into SQL strings directly. This applies even when
the value looks safe or has already been sanitized.

**Give every global symbol a unique prefix of four or more characters.**

Functions, classes, hooks, options, post meta keys, table names, and constants
all live in the global WordPress namespace. A prefix of four or more characters
specific to your plugin or theme avoids collisions. Pick one prefix and use it
everywhere.

## Smallest thing that works

A code snippet before a plugin; a native WordPress feature or an existing
trusted plugin before new code. Consult `read_guidance('minimal-code')` before
deciding what to build. The laziness ladder applies in full here: if a hook or
filter solves the problem, write the hook, not the plugin.

## Before you submit

The most common reasons a plugin or theme is held in review, and where to fix
each one:

- Security (direct SQL, missing escaping, missing nonce or capability checks,
  arbitrary file operations): `wp-security`
- Plugin structure, header format, lifecycle functions (activation, deactivation,
  uninstall), and enqueueing: `wp-plugin-structure`
- Coding standards, proper use of WordPress APIs, and translation-readiness:
  `wp-standards-i18n`
- Readme format, plugin naming rules, and trademark compliance:
  `wp-readme-naming`
- Theme-specific rules (template hierarchy, required files, child-theme
  compatibility): `wp-themes`
- Block development (block.json, server-side rendering, block supports,
  accessibility): `wp-blocks`
- WooCommerce extension requirements (HPOS compatibility, hooks vs. direct DB
  calls, data store APIs): `wc-extension`

Work through every item that applies to your submission before you declare it
done.

## Verify before you finish

If Plugin Check (`wp plugin check`) is available, run it against your plugin and
fix every error and warning it reports before submitting. If `phpcs` is
installed with the WordPress Coding Standards ruleset, run that too.

```sh
wp plugin check my-plugin
phpcs --standard=WordPress my-plugin/
```

If neither tool is available in your environment, tell the author to run Plugin
Check before submitting. See `read_guidance('environment')` to confirm what is
installed before assuming.

## Router

| Topic | File |
|---|---|
| Security, sanitization, escaping, nonces | `wp-security` |
| Plugin structure and lifecycle | `wp-plugin-structure` |
| Coding standards and internationalization | `wp-standards-i18n` |
| Readme, naming, and trademarks | `wp-readme-naming` |
| Theme rules | `wp-themes` |
| Block development | `wp-blocks` |
| WooCommerce extensions | `wc-extension` |
