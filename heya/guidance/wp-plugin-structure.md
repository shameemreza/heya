---
name: wp-plugin-structure
description: WordPress plugin structure. File-access guards, prefixing every global symbol, enqueueing, lifecycle hooks, the Settings API, REST permission callbacks, and using the libraries WordPress bundles.
---

# WordPress plugin structure

Every rule in this file applies to every plugin you write or modify. Read
`wp-security` alongside this file; security is not a separate concern.

## File-access guard

Every PHP file that is not the plugin entry point must refuse direct HTTP
access. Put this at the very top, before any other code:

```php
defined( 'ABSPATH' ) || exit;
```

`ABSPATH` is defined by `wp-load.php`. If the file is loaded directly through
the web server, `ABSPATH` is not defined and execution stops immediately.

The uninstall file is a special case. WordPress sets `WP_UNINSTALL_PLUGIN`
before loading it; guard `uninstall.php` with that constant instead:

```php
if ( ! defined( 'WP_UNINSTALL_PLUGIN' ) ) {
    exit;
}
```

Do not delete plugin data from a deactivation hook. Deactivation is reversible.
Uninstall is not. Only `uninstall.php` (or an uninstall callback registered
with `register_uninstall_hook`) should delete options, custom tables, or
uploaded files.

## Unique prefix on every global symbol

WordPress runs every active plugin in a single PHP process. Every function,
class, constant, global variable, hook name, option key, transient key, custom
post type slug, taxonomy slug, REST namespace, custom table name, and cron hook
name lives in a shared namespace.

Use a unique prefix of four or more characters on all of them. Pick one prefix
and use it everywhere; mixing prefixes within a single plugin causes confusion
and collisions.

Reserved prefixes you must not use: `wp_`, `wordpress_`, `_` (leading
underscore alone), and single common English words such as `the_`, `my_`,
`plugin_`, or `custom_`.

```php
// Wrong — bare function name, easy to collide.
function get_settings() { ... }

// Right — prefixed with the plugin slug.
function myplugin_get_settings() { ... }
```

## No hardcoded paths

Never write a literal filesystem path or a literal `wp-content` segment in your
code. WordPress installations can be configured with non-standard directory
layouts.

Use these functions and constants instead:

- `plugin_dir_path( __FILE__ )` — absolute filesystem path to the current file's
  directory, with a trailing slash.
- `plugin_dir_url( __FILE__ )` — full URL to the current file's directory, with
  a trailing slash.
- `ABSPATH` — WordPress root directory (with trailing slash).
- `WP_CONTENT_DIR` — absolute path to the content directory.
- `WP_PLUGIN_DIR` and `WP_PLUGIN_URL` — absolute path and URL to the plugins
  directory.

```php
// Wrong — hardcoded path breaks non-standard installs.
require_once '/var/www/html/wp-content/plugins/my-plugin/includes/class-loader.php';

// Right — resolved relative to the current file.
require_once plugin_dir_path( __FILE__ ) . 'includes/class-loader.php';
```

## Main file naming and layout

Name the main plugin file after the plugin's slug (for example,
`my-plugin/my-plugin.php`). Do not use generic names such as `index.php`,
`init.php`, or `load.php`; they conflict and reveal nothing about the plugin.

The main file holds the plugin header comment, constants, and the bootstrap
call. Keep it thin. All behavior belongs in included files.

Do not ship obfuscated code, packer output, or minified-only JavaScript without
the corresponding source. The WordPress Plugin Directory requires human-readable
code for review.

## Architecture: hooks, no side effects

Register behavior through WordPress hooks. Do not execute side effects at file
load time (no database calls, no output, no redirects while the file is being
required).

```php
// Wrong — runs immediately at load time.
my_plugin_register_settings();

// Right — deferred to the appropriate hook.
add_action( 'admin_init', 'my_plugin_register_settings' );
```

Prefer classes over loose functions to avoid name collisions and to group
related behavior. Gate admin-only code behind `is_admin()` checks so it never
runs on public pages.

## Enqueueing scripts and styles

Register and enqueue scripts and styles through `wp_enqueue_script` and
`wp_enqueue_style` on the `wp_enqueue_scripts` hook (front end) or
`admin_enqueue_scripts` hook (admin). Never print raw `<script>` or `<style>`
tags in template output.

```php
add_action( 'wp_enqueue_scripts', 'myplugin_enqueue_assets' );

function myplugin_enqueue_assets() {
    wp_enqueue_style(
        'myplugin-styles',
        plugin_dir_url( __FILE__ ) . 'assets/style.css',
        [],
        '1.0.0'
    );

    wp_enqueue_script(
        'myplugin-script',
        plugin_dir_url( __FILE__ ) . 'assets/script.js',
        [ 'jquery' ],
        '1.0.0',
        true
    );
}
```

For small inline assets, attach them to an already-enqueued handle with
`wp_add_inline_style` or `wp_add_inline_script`. Do not print them directly:

```php
// Wrong — raw inline tag in output.
echo '<style>.myplugin-box { color: red; }</style>';

// Right — attached to an enqueued handle.
wp_add_inline_style( 'myplugin-styles', '.myplugin-box { color: red; }' );
```

Use the libraries WordPress bundles (jQuery, Backbone, Underscore, SimplePie,
PHPMailer, and others). Do not ship your own copy of a bundled library and do
not load code assets from a CDN. Serving executable code from a third-party
server is not permitted in the Plugin Directory.

## Lifecycle hooks

Register activation and deactivation hooks at the top level of the main plugin
file, not inside any function or hook callback. Both take the main plugin file's
`__FILE__` as the first argument:

```php
register_activation_hook( __FILE__, 'myplugin_activate' );
register_deactivation_hook( __FILE__, 'myplugin_deactivate' );
```

On activation, flush rewrite rules only after you have registered any custom
post types or taxonomies:

```php
function myplugin_activate() {
    myplugin_register_post_types();
    flush_rewrite_rules();
}
```

Do not redirect from an activation hook. WordPress does not reliably execute
the redirect during plugin activation and the pattern is widely misused. Set a
transient instead and show the message through `admin_notices`:

```php
function myplugin_activate() {
    set_transient( 'myplugin_activation_notice', true, 60 );
}

add_action( 'admin_notices', 'myplugin_show_activation_notice' );

function myplugin_show_activation_notice() {
    if ( ! get_transient( 'myplugin_activation_notice' ) ) {
        return;
    }
    delete_transient( 'myplugin_activation_notice' );
    echo '<div class="notice notice-success is-dismissible"><p>'
        . esc_html__( 'My Plugin is active.', 'my-plugin' )
        . '</p></div>';
}
```

## Settings API

Use the Settings API for plugin options: `register_setting`,
`add_settings_section`, and `add_settings_field`. Register from the
`admin_init` hook, not from `init` or at file load time.

Always provide a `sanitize_callback` on `register_setting`. Use
`add_settings_error` to surface validation failures instead of silently
discarding bad input:

```php
add_action( 'admin_init', 'myplugin_register_settings' );

function myplugin_register_settings() {
    register_setting(
        'myplugin_options_group',
        'myplugin_option_key',
        [
            'sanitize_callback' => 'myplugin_sanitize_options',
            'default'           => [],
        ]
    );

    add_settings_section(
        'myplugin_main_section',
        __( 'General', 'my-plugin' ),
        '__return_false',
        'myplugin-settings'
    );

    add_settings_field(
        'myplugin_api_key',
        __( 'API key', 'my-plugin' ),
        'myplugin_render_api_key_field',
        'myplugin-settings',
        'myplugin_main_section'
    );
}

function myplugin_sanitize_options( $input ) {
    $clean = [];
    $clean['api_key'] = sanitize_text_field( $input['api_key'] ?? '' );

    if ( empty( $clean['api_key'] ) ) {
        add_settings_error(
            'myplugin_option_key',
            'myplugin_empty_api_key',
            __( 'API key cannot be empty.', 'my-plugin' ),
            'error'
        );
    }

    return $clean;
}
```

Choose the right storage mechanism for the data's shape and lifetime: `wp_options`
for plugin-wide settings, transients for cached external data, post meta for
data that belongs to a specific post, user meta for per-user data, and a custom
table only when the data does not fit any of those shapes.

## REST API: permission callbacks

Every route registered with `register_rest_route` must include a
`permission_callback`. A missing or always-true callback on a write endpoint is
a security vulnerability.

Check the specific capability the action requires:

```php
register_rest_route(
    'myplugin/v1',
    '/settings',
    [
        'methods'             => WP_REST_Server::EDITABLE,
        'callback'            => 'myplugin_update_settings',
        'permission_callback' => function() {
            return current_user_can( 'manage_options' );
        },
        'args'                => [
            'api_key' => [
                'type'              => 'string',
                'sanitize_callback' => 'sanitize_text_field',
            ],
        ],
    ]
);
```

Use `__return_true` as the `permission_callback` only for an intentionally
public read endpoint where no authentication or authorization is needed. Every
other endpoint must check a real capability.

Read data from the `WP_REST_Request` object, not from superglobals. Declare
`args` with `type` and `sanitize_callback` or `validate_callback` in the route
definition so WordPress validates and sanitizes inputs before your callback runs.
