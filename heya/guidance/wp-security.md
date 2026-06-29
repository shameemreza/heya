---
name: wp-security
description: WordPress security. Escape output by context, sanitize every input, verify nonces, check capabilities, use prepared SQL, avoid forbidden functions, handle uploads and external requests safely, and honor privacy.
---

# WordPress security

Apply every rule in this file to every plugin, theme, or snippet you write or
modify. None of these rules are optional.

## Escape output by context

Escape at the point of output, never earlier. The right escaping function
depends on where the value appears.

| Context | Function |
|---|---|
| HTML text content | `esc_html` |
| HTML attribute value | `esc_attr` |
| URL in `href`, `src`, `action` | `esc_url` |
| `<textarea>` content | `esc_textarea` |
| Inline JavaScript value | `esc_js` |
| Rich HTML with an allowlist | `wp_kses_post` or `wp_kses` |

Never echo a raw variable. Escape late.

```php
// Wrong: raw variable echoed directly.
echo '<p>' . $user_input . '</p>';

// Right: escaped at the point of output.
echo '<p>' . esc_html( $user_input ) . '</p>';
```

For rich text (post content, widget text) where some HTML must be preserved,
use `wp_kses_post` to strip everything outside the allowed tag set:

```php
echo wp_kses_post( $content );
```

For URLs:

```php
echo '<a href="' . esc_url( $link ) . '">' . esc_html( $label ) . '</a>';
```

## Sanitize every input

Treat every superglobal (`$_POST`, `$_GET`, `$_REQUEST`, `$_FILES`,
`$_COOKIE`, `$_SERVER`) as hostile. Apply `wp_unslash` first to strip the
magic-quotes layer WordPress adds, then the most specific sanitizer available.

```php
// Wrong: raw superglobal used directly.
$name = $_POST['name'];

// Right: unslash, then sanitize.
$name = sanitize_text_field( wp_unslash( $_POST['name'] ?? '' ) );
```

Common sanitization functions:

| Data type | Function |
|---|---|
| Plain text (single line) | `sanitize_text_field` |
| Multi-line text | `sanitize_textarea_field` |
| Email address | `sanitize_email` |
| URL | `esc_url_raw` (for storage); `sanitize_url` |
| Integer | `absint` |
| Slug or key | `sanitize_key` |
| File name | `sanitize_file_name` |
| Rich HTML | `wp_kses_post` |

Passwords are a special case: validate length and form, but do not sanitize or
alter the value before hashing.

## Validate with an allowlist

When a value must be one of a known set, reject anything that is not on the
list before storing or acting on it.

```php
$allowed_types = [ 'post', 'page', 'attachment' ];
if ( ! in_array( $type, $allowed_types, true ) ) {
    wp_die( esc_html__( 'Invalid type.', 'my-plugin' ) );
}
```

The third argument `true` to `in_array` enforces strict type comparison.

## Nonces and CSRF protection

Every form submission, AJAX handler, and REST endpoint that modifies data needs
a nonce verified before any action is taken.

Generate the nonce field in the form:

```php
wp_nonce_field( 'my_plugin_save_settings', 'my_plugin_nonce' );
```

Verify it in the handler:

```php
check_admin_referer( 'my_plugin_save_settings', 'my_plugin_nonce' );
```

For AJAX:

```php
check_ajax_referer( 'my_plugin_ajax_action', 'nonce' );
```

For manual verification when you need to branch:

```php
if ( ! wp_verify_nonce( wp_unslash( $_POST['my_plugin_nonce'] ?? '' ), 'my_plugin_save_settings' ) ) {
    wp_die( esc_html__( 'Nonce check failed.', 'my-plugin' ) );
}
```

A nonce proves the request came from a form you generated. It is not
authorization. Always pair it with a capability check.

## Authorization with capabilities

Check the current user's capability before any privileged action. Use the most
specific capability that applies.

```php
// Wrong: checks a role, not a capability.
if ( in_array( 'administrator', (array) wp_get_current_user()->roles, true ) ) { ... }

// Right: check the capability that the action actually requires.
if ( ! current_user_can( 'manage_options' ) ) {
    wp_die( esc_html__( 'You do not have permission to do this.', 'my-plugin' ) );
}
```

Never rely on `is_admin()` as a permission check. It tests whether the current
URL is in the admin area, not whether the current user has any particular right.
Always call `current_user_can` with the specific capability.

## Prepared SQL

Never build SQL by interpolating variables into a query string. Use
`$wpdb->prepare()` with `%d` for integers, `%f` for floats, and `%s` for
strings. Use `%i` for identifiers (table names, column names) when available.

```php
// Wrong: variable interpolated directly into SQL.
$results = $wpdb->get_results( "SELECT * FROM {$wpdb->prefix}orders WHERE user_id = $user_id" );

// Right: $wpdb->prepare() with placeholders.
$results = $wpdb->get_results(
    $wpdb->prepare(
        'SELECT * FROM %i WHERE user_id = %d',
        $wpdb->prefix . 'orders',
        absint( $user_id )
    )
);
```

This applies even when the value looks safe or has been sanitized earlier.
Sanitization and SQL escaping are separate concerns.

`esc_sql()` is not a substitute for `$wpdb->prepare()`. Do not build a query by
concatenating `esc_sql( $value )`; always use `$wpdb->prepare()` with
placeholders.

## File uploads

Never handle raw `$_FILES` and call `move_uploaded_file` directly. Use
`wp_handle_upload` instead. It validates the file against allowed MIME types
and moves the file to the uploads directory safely.

```php
$overrides = [ 'test_form' => false ];
$file = wp_handle_upload( $_FILES['my_file'], $overrides );

if ( isset( $file['error'] ) ) {
    return new WP_Error( 'upload_error', $file['error'] );
}
```

Always check the MIME type after upload with `wp_check_filetype` before
allowing the uploaded file to be used:

```php
$filetype = wp_check_filetype( basename( $file['file'] ), null );
if ( ! $filetype['type'] ) {
    wp_delete_file( $file['file'] );
    return new WP_Error( 'invalid_type', 'File type not permitted.' );
}
```

## External requests

Use `wp_remote_get` and `wp_remote_post` for HTTP requests instead of
`curl_exec` or `file_get_contents`. This respects WordPress proxy settings and
allows filtering by other plugins.

When the URL comes from user input or a stored setting, use
`wp_safe_remote_get` or `wp_safe_remote_post` to prevent SSRF (server-side
request forgery). These functions block requests to internal addresses.

```php
// For a hard-coded, trusted URL.
$response = wp_remote_get( 'https://api.example.com/data' );

// For any URL that originates from user input.
$response = wp_safe_remote_get( esc_url_raw( $user_supplied_url ) );

if ( is_wp_error( $response ) ) {
    // Handle the error.
}
$body = wp_remote_retrieve_body( $response );
```

## Forbidden functions and patterns

Do not use any of the following. They create remote code execution, SQL
injection, or arbitrary file access vulnerabilities.

**Arbitrary code execution:**
`eval`, `create_function`, `assert` with a string argument,
`preg_replace` with the `/e` modifier, `exec`, `system`, `shell_exec`,
`passthru`, `popen`, `proc_open`.

**Unsafe deserialization:**
`unserialize` on any user-controlled input. PHP object deserialization can
trigger arbitrary code execution through magic methods. Use `json_decode`
instead when you control the data format.

```php
// Wrong: unserialize on stored or user-supplied data.
$data = unserialize( get_option( 'my_plugin_data' ) );

// Right: store as JSON, decode safely.
$data = json_decode( get_option( 'my_plugin_data' ), true );
```

**Raw database access:**
`mysql_*` functions (removed in PHP 7). Use `$wpdb->prepare()` with
`$wpdb->get_results`, `$wpdb->get_row`, `$wpdb->get_var`, `$wpdb->query`.

**Debug output in production:**
`var_dump`, `print_r`, and `error_log` must be gated behind `WP_DEBUG` or
removed before submission. Never leave them in production code paths.

## Arbitrary-code inputs

Never accept PHP code, raw JavaScript, or unfiltered HTML as a plugin setting
or shortcode attribute. If a setting accepts HTML, run it through `wp_kses_post`
or a custom `wp_kses` allowlist before storage and again before output.

## Privacy

When your plugin stores personal data, you must register a data exporter and
an eraser so WordPress can honor erasure requests (GDPR Article 17 and similar
laws).

```php
// Register the exporter.
add_filter( 'wp_privacy_personal_data_exporters', 'my_plugin_register_exporter' );

function my_plugin_register_exporter( $exporters ) {
    $exporters['my-plugin'] = [
        'exporter_friendly_name' => __( 'My Plugin', 'my-plugin' ),
        'callback'               => 'my_plugin_export_user_data',
    ];
    return $exporters;
}
```

Register an eraser the same way using `wp_privacy_personal_data_erasers`.
Declare what data your plugin collects with `wp_add_privacy_policy_content` so
it appears in the site's privacy policy.
