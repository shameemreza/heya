# Releasing Heya

Heya publishes to PyPI as `heya-agent` (the command stays `heya`). Releases run
through GitHub Actions with trusted publishing, so no PyPI token is ever stored.

## One-time setup (already done)

- A PyPI trusted publisher for project `heya-agent`, owner `shameemreza`, repo
  `heya`, workflow `release.yml`, environment `pypi`.
- Optional: a TestPyPI trusted publisher with the same values but environment
  `testpypi`, to rehearse releases.

## Every release

1. Make sure `main` is green. CI runs the test suite on Python 3.11, 3.12, and
   3.13 for every push and pull request. Do not release on a red build.

2. Bump the version in `pyproject.toml`. Use semantic versioning: patch for
   fixes (`0.0.2`), minor for new features (`0.1.0`), major for breaking
   changes.

3. Move the `## [Unreleased]` notes in `CHANGELOG.md` under a new version
   heading with today's date, and add the new compare links at the bottom.

4. Test the build locally before tagging:

   ```bash
   python -m pip install build
   python -m build
   python -m pip install --force-reinstall dist/heya_agent-*.whl
   heya --version
   ```

5. (Optional but recommended) Rehearse on TestPyPI. In the Actions tab, run the
   `release` workflow manually (`workflow_dispatch`); it builds and publishes to
   TestPyPI. Then install from there into a clean environment and smoke-test:

   ```bash
   pipx install --index-url https://test.pypi.org/simple/ \
     --pip-args="--extra-index-url https://pypi.org/simple/" heya-agent
   ```

6. Tag and push. The tag is what triggers the real PyPI publish:

   ```bash
   git tag v0.0.2
   git push origin v0.0.2
   ```

   The `release` workflow builds and publishes to PyPI. Confirm the new version
   shows at https://pypi.org/project/heya-agent/.

7. Verify the published package installs and runs:

   ```bash
   pipx install heya-agent   # or: pipx upgrade heya-agent
   heya --version
   ```

## Handling a reported bug

1. Reproduce it locally from an editable install (`pip install -e .`).
2. Write a failing test that captures the bug.
3. Fix it, watch the test pass, run the full suite.
4. Add a `### Fixed` line under `## [Unreleased]` in the changelog.
5. Release a patch version with the steps above.
