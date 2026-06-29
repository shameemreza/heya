---
name: wp-standards-i18n
description: WordPress coding standards and internationalization. WPCS style, translation functions, the text domain, and translator comments so every string can be localized.
---

# WordPress coding standards and internationalization

Apply these rules to every plugin, theme, or snippet you write or modify. They
cover formatting, naming, regex hygiene, and internationalization.

## Formatting and style

WordPress Core follows a strict formatting convention. Use tabs for indentation,
not spaces. Place a space inside every pair of parentheses in control structures,
function calls, and function definitions.

```php
// Wrong: spaces for indent, no spaces inside parens.
if($active) {
    return $value;
}

// Right: tab indent, spaces inside parens.
if ( $active ) {
    return $value;
}
```

Place the opening brace on the same line as the control structure. For
single-line closures it is acceptable to keep the brace on the same line as the
function keyword.

### Yoda conditions

Write comparisons with the constant or literal on the left. This prevents
accidental assignment when `==` is used instead of `===`.

```php
// Wrong: variable on the left.
if ( $status === 'active' ) { ... }

// Right: Yoda condition, literal on the left.
if ( 'active' === $status ) { ... }
```

### Naming conventions

- Functions and variables: `lowercase_with_underscores`.
- Classes: `CapitalizedWords` (PascalCase).
- Constants: `ALL_CAPS_WITH_UNDERSCORES`.
- All functions, classes, and globals must be prefixed with a unique slug to
  avoid collisions with other plugins and WordPress Core.

### Multi-line arrays

Include a trailing comma after the last item in a multi-line array. This keeps
diffs clean when items are added or removed later.

```php
$config = [
    'option_a' => true,
    'option_b' => 'value',
];
```

### Type declarations

Use scalar type declarations and return types where the minimum PHP version of
the project supports them. They make intent explicit and catch class-of-error
bugs at the boundary.

```php
function my_plugin_get_label( string $key ): string {
    return $labels[ $key ] ?? '';
}
```

## Prefer built-in functions over regex

WordPress and PHP provide functions for common checks. Prefer them over rolling
a custom pattern.

| Task | Prefer |
|---|---|
| String contains | `str_contains` (PHP 8+) or `strpos` |
| Valid email | `is_email` |
| Validate and filter | `filter_var` with `FILTER_*` constants |
| Parse a URL | `parse_url` |
| Check a file extension | `wp_check_filetype` |

When a regular expression is unavoidable, avoid catastrophic backtracking by
keeping patterns simple and possessive quantifiers minimal. Never interpolate
user input into a pattern without first calling `preg_quote` with the delimiter.

```php
// Wrong: user input in a regex pattern without quoting.
preg_match( '/' . $user_term . '/i', $haystack );

// Right: user input quoted before use.
preg_match( '/' . preg_quote( $user_term, '/' ) . '/i', $haystack );
```

For broader regex guidance, load `read_guidance('avoid-regex')`.

## Internationalization

Every user-facing string must be wrapped in a translation function so the plugin
or theme can be fully localized.

### Text Domain

The `Text Domain` header in the plugin or theme file must exactly match the
plugin or theme slug as a string literal. Never use a variable or a constant as
the text domain argument in translation calls.

```php
// Plugin header.
/*
 * Plugin Name: My Plugin
 * Text Domain: my-plugin
 */

// Wrong: variable as text domain.
$domain = 'my-plugin';
__( 'Settings saved.', $domain );

// Right: string literal matches the slug.
__( 'Settings saved.', 'my-plugin' );
```

### Translation functions

| Function | Use |
|---|---|
| `__( 'text', 'slug' )` | Return a translated string |
| `_e( 'text', 'slug' )` | Echo a translated string |
| `_x( 'text', 'context', 'slug' )` | Return with disambiguation context |
| `_n( 'single', 'plural', $count, 'slug' )` | Singular/plural form |
| `esc_html__( 'text', 'slug' )` | Return, escaped for HTML content |
| `esc_attr__( 'text', 'slug' )` | Return, escaped for an HTML attribute |
| `esc_html_e( 'text', 'slug' )` | Echo, escaped for HTML content |
| `esc_attr_e( 'text', 'slug' )` | Echo, escaped for an HTML attribute |

Use the escaping variants whenever the result is output directly into HTML. They
escape and translate in a single call.

```php
// Escape and translate.
esc_html__( 'Settings saved.', 'my-plugin' );
esc_attr_e( 'Enter your name', 'my-plugin' );
```

Never echo a translated string without escaping it.

### Plurals with _n(

Use `_n(` when the string must change between singular and plural. Pass `$count`
through `number_format_i18n` for display.

```php
$label = sprintf(
    _n( '%s item found.', '%s items found.', $count, 'my-plugin' ),
    number_format_i18n( $count )
);
echo esc_html( $label );
```

### Translator comments for placeholders

When a string contains `printf`/`sprintf` placeholders, add a translator comment
immediately above the function call. The comment tells translators what each
placeholder will contain so they can reorder them correctly for their language.

```php
// Wrong: no comment, translators cannot identify the placeholder.
printf( __( 'Welcome, %s.', 'my-plugin' ), esc_html( $name ) );

// Right: translator comment immediately before the call.
/* translators: %s: user display name. */
printf( esc_html__( 'Welcome, %s.', 'my-plugin' ), esc_html( $name ) );
```

The comment format is `/* translators: %s: description. */`. Use `%1$s`,
`%2$s`, etc. for multiple placeholders and describe each one.

### Load translations no earlier than init

Do not call translation functions before the `init` hook. The common mistake is
calling them at file scope, at the top level of the file before any hook has
fired and before WordPress has bootstrapped its locale. Wrap every translatable
string inside a callback that runs on `init` or later.

```php
// Wrong: called at file scope, before any hook.
$label = __( 'Settings', 'my-plugin' );

// Right: called inside a callback hooked no earlier than init.
function my_plugin_init() {
    $label = __( 'Settings', 'my-plugin' );
    // Use $label.
}
add_action( 'init', 'my_plugin_init' );
```

Since WordPress 4.6, translations for plugins hosted on WordPress.org load
just-in-time, so an explicit `load_plugin_textdomain` call is often unnecessary.
If you do call it, hook it on `init`:

```php
function my_plugin_load_textdomain() {
    load_plugin_textdomain( 'my-plugin', false, dirname( plugin_basename( __FILE__ ) ) . '/languages/' );
}
add_action( 'init', 'my_plugin_load_textdomain' );
```

For plugins that target WordPress 6.7 and later, calling translation functions
too early triggers a `_doing_it_wrong` notice, so keep all translation work on
`init` or later.

## UI text in sentence case

All user-facing labels, headings, button text, notices, and error messages must
use sentence case: capitalize only the first word and proper nouns. Do not use
title case for interface labels.

For detailed guidance on specific label patterns, load
`read_guidance('sentence-case-ui')`.
