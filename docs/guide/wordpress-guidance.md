# WordPress guidance

Heya ships guidance for building WordPress plugins, themes, and code snippets
that follow WordPress.org best practices and are secure by default. When a task
involves WordPress, Heya reads this guidance and follows it, so what it writes
is ready for review.

## What it covers

- `wordpress` is the entry point: the must-follow rules and a before-you-submit
  checklist. It routes to the rest.
- `wp-security` covers escaping output, sanitizing input, nonces, capability
  checks, prepared SQL, forbidden functions, uploads, external requests, and
  privacy.
- `wp-plugin-structure` covers file-access guards, prefixing, enqueueing, the
  plugin lifecycle, the Settings API, REST permission callbacks, and bundled
  libraries.
- `wp-standards-i18n` covers the WordPress Coding Standards and making every
  string translatable.
- `wp-readme-naming` covers the readme, the headers, naming and trademarks, and
  the Plugin Directory Guidelines.
- `wp-themes` covers the theme review requirements: the style.css headers, the
  screenshot, required template hooks, the plugin-territory rule, sanitizing
  Customizer input, accessibility, and child themes.
- `wp-blocks` covers block development: block.json, the current apiVersion, the
  static, dynamic, and interactive block models, and deprecations.
- `wc-extension` covers WooCommerce extensions: HPOS and block checkout
  compatibility, CRUD objects, logging, and naming.

## Verify before you submit

Heya will run Plugin Check or PHPCS with the WordPress ruleset when they are
available in your environment, and otherwise reminds you to run Plugin Check
before submitting. You stay in control of what ships.

## Make it yours

Every file is a default. Point `[guidance] paths` at your own folder to add or
override any of it with your team's conventions.
