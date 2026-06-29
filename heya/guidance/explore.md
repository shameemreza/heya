---
name: explore
description: How to understand a project before judging it. Map it, find the entry points, follow the code. Includes how to read a WordPress plugin. Override it with your own explore guidance.
---

# Explore a project

Understand the code before you judge it. Map first, then read with purpose.

## Get oriented

- Call `list_files` for a tree of the project, then read the entry points (the
  main script, the package or plugin header, the config).
- Use `search_files` to find a thing by name (a function, a hook, a class, a
  setting), then open that file and follow its includes and imports.
- Read enough to be sure. A confident answer built on a file you did not open is
  a guess.

## Read a WordPress plugin

- A `Plugin Name:` header, a `style.css` with a theme header, or a `theme.json`
  marks a WordPress project. When you will write or change its code, read
  `read_guidance('wordpress')` first and follow it.
- The main file is the one with the `Plugin Name:` header. Start there.
- Read `readme.txt` for the stable tag and what the plugin claims to do.
- Follow `include` and `require` to the files that do the work.
- Map the hooks: `add_action` and `add_filter` show what the plugin touches and
  when. Look for the callbacks they point to.
- Check `composer.json` or `package.json` for dependencies and build steps.

## Confirm, do not assume

Confirm the WordPress, WooCommerce, and PHP versions and the environment rather
than assuming them. See `read_guidance('environment')`.

## Say what you found

State what you read and what you concluded, and name anything you are still
unsure about. Being clear about the edge of your knowledge is part of the answer.
