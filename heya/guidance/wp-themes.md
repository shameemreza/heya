---
name: wp-themes
description: WordPress theme requirements for review. The style.css headers, the screenshot, required template hooks, the plugin-territory ban, sanitizing Customizer input, accessibility basics, and child themes.
---

# WordPress theme review requirements

These rules apply to both classic and block themes submitted to or hosted on
WordPress.org. A theme that fails any of these requirements will not pass
review.

## style.css header

Every theme requires a `style.css` at the root of the theme folder. The comment
block at the top of that file is the theme's header. All of the following fields
are required:

```css
/*
Theme Name:  My Theme
Description: A short description of the theme.
Version:     1.0.0
Author:      Your Name
Text Domain: my-theme
Requires at least: 6.4
Tested up to:      6.7
Requires PHP:      7.4
License:     GNU General Public License v2 or later
License URI: https://www.gnu.org/licenses/gpl-2.0.html
*/
```

The version numbers above are illustrative. Set `Requires at least`,
`Tested up to`, and `Requires PHP` to the versions you actually require and test
against, not to any fixed value copied from an example.

`Text Domain` must match the theme's slug (the folder name). Every translatable
string in the theme must use that text domain. Do not use a text domain that
belongs to another project or to WordPress core.

## Screenshot

Include a `screenshot.png` or `screenshot.jpg` in the theme root. The image
must be in a 4:3 ratio and no larger than 1200 by 900 pixels. Smaller
screenshots are fine; larger ones are not.

The screenshot must show the theme's own design. It must not contain advertising,
third-party logos, stock photos with restrictive licenses, or any branding that
does not belong to the theme author.

## Required template hooks for classic themes

A classic theme's `header.php` must contain a DOCTYPE declaration, the
`<html>` opening tag with `language_attributes()`, and a call to `wp_head()`
immediately before `</head>`. The `<body>` tag must output `body_class()`:

```php
<!DOCTYPE html>
<html <?php language_attributes(); ?>>
<head>
    <meta charset="<?php bloginfo( 'charset' ); ?>">
    <?php wp_head(); ?>
</head>
<body <?php body_class(); ?>>
<?php wp_body_open(); ?>
```

`wp_body_open()` fires the `wp_body_open` action immediately after the opening
`<body>` tag. Plugins use this hook to inject content (for example, tag manager
noscript blocks). Omitting it breaks those integrations.

`footer.php` must call `wp_footer()` immediately before `</body>`:

```php
<?php wp_footer(); ?>
</body>
</html>
```

Posts and pages displayed in the loop must output `post_class()` on their
wrapper element so plugins can target them with CSS or JavaScript.

For classic themes, every required template file must exist (`index.php`,
`comments.php`, and so on). For block themes, a complete `templates/index.html`
is required. Block themes must not contain PHP template files that duplicate
the block template hierarchy.

## No plugin territory

A theme controls presentation. It must not add functionality that belongs in a
plugin. The following are not permitted in a theme:

- Custom post types or custom taxonomies.
- Shortcodes.
- Analytics or tracking code.
- SEO features (meta tags, sitemaps, structured data).
- Contact forms or other form-processing logic.
- Custom admin pages or admin menu items.

Options belong in the Customizer or in `theme.json`. Do not create standalone
options pages.

## Customizer options

Sanitize and validate every value a user can submit through the Customizer. Use
the appropriate sanitization function for each type of input:

```php
$wp_customize->add_setting(
    'mytheme_header_color',
    [
        'default'           => '#ffffff',
        'sanitize_callback' => 'sanitize_hex_color',
    ]
);
```

`sanitize_hex_color` accepts `#rgb` and `#rrggbb` values and returns an empty
string for anything else. Use it for any color picker setting.

Store all theme options under a single prefixed key (for example
`mytheme_options`) rather than creating one option record per setting. This
keeps the database clean and makes export and import straightforward.

## Bundled assets and credits

List the copyright and license of every bundled asset in the `readme.txt` or a
dedicated `credits.txt` file. Bundled assets include fonts, images, icons,
JavaScript libraries, and PHP libraries. Every bundled asset must be compatible
with the GPL.

Do not load fonts, scripts, or stylesheets from external servers (Google Fonts,
jsDelivr, unpkg, and so on) without the user's explicit consent. Load assets
locally or provide a setting that lets the user opt in.

You may include one credit link in the theme's footer. More than one credit link
is not permitted.

## Accessibility basics

A theme that ships with these gaps will require corrections before it passes
review:

- **Skip link:** The first focusable element in the page must be a skip link
  that jumps to the main content area. It must be visible (or become visible) on
  keyboard focus.
- **Keyboard focus indicator:** Every interactive element (links, buttons, form
  fields) must have a visible focus indicator. Do not remove the browser default
  outline without providing an equivalent.
- **Heading hierarchy:** Headings must not skip levels. A page with an `<h1>`
  followed immediately by an `<h3>` (skipping `<h2>`) fails this check.
- **Form labels:** Every form field must have an associated `<label>` element or
  an `aria-label` attribute.
- **Color contrast:** Text must have sufficient contrast against its background.
  Follow WCAG AA as a minimum target.

## Child theme support

A parent theme must not break when a child theme overrides one of its templates.
Two functions resolve theme directories, and they are not interchangeable:

- `get_template_directory()` returns the parent theme's directory. A parent
  theme's bundled files always live in the parent, so a parent theme loading its
  own includes must use this function.
- `get_stylesheet_directory()` returns the active theme's directory, which is
  the child when a child theme is active. A child theme loading its own files
  uses this function.

```php
// In a parent theme, loading the parent's own bundled file.
// Correct: the parent's files always live in the parent directory.
require_once get_template_directory() . '/inc/functions.php';

// In a child theme, loading the child's own bundled file.
// Correct: get_stylesheet_directory() resolves to the active (child) theme.
require_once get_stylesheet_directory() . '/inc/customizations.php';
```

Do not use `get_stylesheet_directory()` to `require` a parent theme's file. When
a child theme is active it resolves to the child, and if the child does not
contain that file the require fatals.

For templates a child theme should be able to override, use `get_template_part()`
or `locate_template()` rather than a hardcoded `require`. WordPress resolves
these through the child theme first, then falls back to the parent, so a child
can override a template without the parent erroring.

## Code quality

Enable `WP_DEBUG` and `WP_DEBUG_LOG` and work through any PHP notices or
warnings the theme generates. A theme must produce zero PHP notices or warnings
under `WP_DEBUG`. Common sources of notices are undefined variables, direct
access to `$_GET` or `$_POST` without `isset()` checks, and calling functions
that do not exist on all supported PHP versions.

Do not ship demo content that persists after the theme is activated. If you
include sample images, make sure they are properly licensed and noted in the
credits. Import-only demo content (through a one-time import flow) is acceptable;
content that inserts posts or pages on activation is not.

Before creating the zip for submission, exclude version-control directories and
editor configuration files:

```
.git/
.svn/
.gitignore
.DS_Store
.editorconfig
node_modules/
```

## theme.json

Block themes and block-aware classic themes use `theme.json` to declare design
tokens and control the block editor's settings. The style hierarchy determines
which values win:

1. Core WordPress defaults.
2. `theme.json` in the active theme (or parent theme for child themes).
3. `theme.json` in the child theme (overrides the parent).
4. User customizations stored in the database (from the site editor or
   Customizer).

User customizations are stored in the database and take precedence over
`theme.json`. If a file edit appears to have no effect, a stored user
customization is likely overriding it. Use the site editor's "reset to defaults"
action to clear stored customizations during development.

A `theme.json` can define:

- `settings`: palette, typography, spacing, layout defaults, and which
  block-editor controls are enabled.
- `styles`: global CSS rules and element-level rules that the editor and the
  front end both use.
- `customTemplates` and `templateParts`: declarations that appear in the site
  editor.
- `patterns`: pattern slugs to include from the pattern directory.
- Style variations: additional `theme.json` files placed in a
  `styles/` subdirectory that users can select from the site editor.
