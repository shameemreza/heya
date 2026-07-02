---
name: avoid-regex
description: When to avoid regular expressions and what to use instead.
---

# Avoid regex

Regular expressions are powerful but easy to get wrong. Prefer simpler
alternatives unless the input is genuinely irregular.

## Prefer string methods

Before reaching for a regex, check whether a built-in string method does the
job.

| Task | Instead of regex, use |
|---|---|
| Does a string start with a prefix? | `str.startswith()` (Python) / `str_starts_with()` (PHP) |
| Does it contain a substring? | `in` operator (Python) / `str_contains()` (PHP 8+) |
| Split on a fixed delimiter | `str.split()` / `explode()` |
| Strip leading/trailing characters | `str.strip()` / `trim()` |
| Replace a fixed substring | `str.replace()` / `str_replace()` |

String methods are faster, easier to read, and cannot catastrophically backtrack.

## Use real parsers for structured formats

Do not parse HTML, XML, JSON, URLs, or email addresses with regex. Use the
parser built for the format.

- **HTML/XML**: `DOMDocument` (PHP), `BeautifulSoup` (Python), `html.parser`
- **JSON**: `json_decode` / `json.loads`
- **URLs**: `parse_url` / `urllib.parse`
- **Email**: validate with a library or a simple `filter_var($v, FILTER_VALIDATE_EMAIL)`

## WordPress / PHP specifics

Prefer the WordPress sanitization API over hand-rolled patterns.

- `wp_kses` / `wp_kses_post` to filter HTML (not a regex allowlist)
- `sanitize_text_field`, `sanitize_email`, `esc_url_raw` for common types
- `str_starts_with`, `str_contains`, `str_ends_with` (PHP 8+) for substring checks

## When regex is unavoidable

If you must use a regex, follow these rules:

1. **Anchor it.** Use `^` and `$` (or `\A` / `\z`) to prevent partial matches.
2. **Avoid catastrophic backtracking.** Do not nest quantifiers (`(a+)+`).
   Use possessive quantifiers or atomic groups when your engine supports them.
3. **Comment the intent.** One line above the pattern, say what it matches and why.
4. **Test edge cases.** Empty string, very long input, Unicode, and adversarial
   input that is designed to cause backtracking.
