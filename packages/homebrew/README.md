# Amprealize Homebrew Formula

This directory contains the Homebrew formula for installing Amprealize via `brew`.

## For Users

### Option 1: Install from PyPI (Recommended)
```bash
brew install python@3.11
pip install amprealize
```

### Option 2: Install from Tap (Once Published)

After you publish a tap repo named `SandRiseStudio/homebrew-amprealize` (see below):

```bash
brew tap sandrisestudio/amprealize
brew install amprealize
```

## For Maintainers

### Setting Up the Tap

1. Create a new repository: `github.com/SandRiseStudio/homebrew-amprealize`

2. Copy the formula:
   ```bash
   mkdir -p Formula
   cp amprealize.rb Formula/
   ```

3. Update SHA256 hashes after PyPI publish:
   ```bash
   # Get the SHA256 from PyPI
   curl -sL https://pypi.org/pypi/amprealize/json | jq -r '.urls[] | select(.packagetype=="sdist") | .digests.sha256'
   ```

4. Push to the tap repository

### Updating the Formula

When a new version is released:

1. Update the `url` with the new version
2. Update the `sha256` hash
3. Update resource versions if dependencies changed
4. Test locally:
   ```bash
   brew install --build-from-source ./amprealize.rb
   brew test amprealize
   ```

### CI/CD Integration

Add to `.github/workflows/publish-homebrew.yml`:

```yaml
name: Update Homebrew Formula

on:
  release:
    types: [published]

jobs:
  homebrew:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v4

      - name: Get release version
        id: version
        run: echo "version=${GITHUB_REF#refs/tags/v}" >> $GITHUB_OUTPUT

      - name: Update Homebrew formula
        uses: dawidd6/action-homebrew-bump-formula@v4
        with:
          token: ${{ secrets.HOMEBREW_TAP_TOKEN }}
          tap: sandrisestudio/amprealize
          formula: amprealize
          tag: ${{ github.ref }}
```

## Formula Features

- **Python virtualenv**: Isolated Python environment
- **Shell completions**: Bash, Zsh, Fish auto-generated
- **Optional Podman**: For infrastructure management
- **Data directories**: Managed under `$(brew --prefix)/var/amprealize/`
- **Test suite**: Verifies CLI, doctor, and init commands
