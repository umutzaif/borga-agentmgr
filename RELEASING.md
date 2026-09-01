# Releasing

1. Move the new entries in `CHANGELOG.md` under a fresh `## [X.Y.Z]` heading
   and add the compare link at the bottom.
2. Bump the version in **two** places: `version` in `pyproject.toml` and
   `__version__` in `agentmgr/__init__.py`.
3. Open a PR with those changes; merge to `main` once CI is green.
4. Tag and push:

   ```bash
   git checkout main && git pull
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   ```

5. The `release` workflow (`.github/workflows/release.yml`) fires on the tag:
   it builds the sdist + wheel and creates a GitHub Release with generated
   notes and the artifacts attached.

## Publishing to PyPI (optional)

The PyPI job is gated behind the repository variable `PUBLISH_TO_PYPI`, so it
does nothing until you opt in. To enable it:

1. Create the `agentmgr` project on PyPI (or reserve the name with a first
   manual upload from a maintainer account).
2. Configure a **Trusted Publisher** on PyPI: GitHub Actions, repository
   `umutzaif/borga-agentmgr`, workflow `release.yml`, environment `pypi`.
   No API token is stored anywhere.
3. In the GitHub repo: create an Environment named `pypi`, then set the
   repository **variable** `PUBLISH_TO_PYPI` to `true`.

The next tag push then also publishes to PyPI via OIDC.

### Dry run against TestPyPI (manual, from a clone)

```bash
python -m build
python -m twine upload --repository testpypi dist/*
pipx install --index-url https://test.pypi.org/simple/ agentmgr
```
