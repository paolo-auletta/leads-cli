# Publishing Leads

This checklist is for cutting a public Leads release.

## Build

```bash
rm -rf dist/
python -m build
python -m twine check dist/*
```

## Publish Package

Publish to TestPyPI first when validating packaging metadata:

```bash
python -m twine upload --repository testpypi dist/*
pipx install --pip-args "--index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/" leads
leads init
```

Publish to PyPI after the TestPyPI install works:

```bash
python -m twine upload dist/*
pipx install leads
leads init
```

## Publish Installers

Host these files from the release branch or tag:

```text
install.sh
install.ps1
```

The README assumes:

```text
https://raw.githubusercontent.com/paoloauletta/leads/main/install.sh
https://raw.githubusercontent.com/paoloauletta/leads/main/install.ps1
```

Update the README if the public repository, branch, or release hosting URL changes.

## Release Checks

Before announcing a release:

```bash
leads version
leads doctor
leads update --check
leads migrate --check
leads skills status
```
