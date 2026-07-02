---
name: sentence-case-ui
description: UI strings use sentence case, not Title Case.
---

# Sentence case in UI strings

UI strings (buttons, labels, headings, menu items, notices, tooltips, and
placeholder text) use sentence case. Capitalize only the first word of the
string and any proper nouns.

This matches WordPress core and WooCommerce admin conventions. When in doubt,
check how core phrases a similar string.

## Right vs. wrong

| Wrong (Title Case) | Right (Sentence case) |
|---|---|
| Save Changes | Save changes |
| Add New Product | Add new product |
| Payment Settings | Payment settings |
| Enable This Feature | Enable this feature |
| Are You Sure? | Are you sure? |

## Proper nouns are always capitalized

Product names, brand names, and technology names keep their own casing regardless
of position.

- WooCommerce, WordPress, PayPal, WooPayments, PHP, REST API

## What counts as a proper noun in a UI string

- The name of the site, store, or product being referenced
- Third-party service names (Stripe, Mailchimp, Google Analytics)
- WordPress itself and its feature names when used as names (Gutenberg, REST API)

## Applies to

Translatable strings (`__()`, `_e()`, `_x()`, `esc_html__()`, etc.),
React component text, settings page labels, admin notices, and any text visible
to the end user or store manager.
