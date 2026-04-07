# Enterprise ↔ OSS Version Coupling

> How `amprealize-enterprise` tracks a known-good OSS revision of `amprealize`.

---

## Version Pin File: `.amprealize-version`

The single source of truth for the current OSS version is the
`.amprealize-version` file in the repository root.  It works like
`.node-version` or `.python-version` — one line, one version:

```
0.1.0
```

All CI jobs, install scripts, and enterprise dependencies should
reference this file rather than hardcoding a version string.

---

## Coupling Mechanisms

### 1. Compatible-release pin (default)

The `[project.optional-dependencies]` enterprise extra in OSS
`pyproject.toml` uses PEP 440 compatible release:

```toml
enterprise = ["amprealize-enterprise~=0.1.0"]   # >=0.1.0, <0.2.0
```

The enterprise repo mirrors this in reverse:

```toml
dependencies = ["amprealize~=0.1.0"]            # >=0.1.0, <0.2.0
```

A **patch bump** (0.1.1) on either side is automatically compatible.
A **minor bump** (0.2.0) is a **breaking boundary** requiring both
sides to update.

### 2. Install from tag (strictest)

Enterprise CI can pin to the exact OSS release tag:

```bash
# Enterprise CI — install exact OSS revision
OSS_VERSION=$(cat .amprealize-version)
pip install "amprealize==${OSS_VERSION}"
python scripts/check_oss_version.py --strict
```

This is the recommended approach for production deployments where
reproducibility is critical. The `--strict` flag rejects any version
that doesn't exactly match `.amprealize-version`.

### 3. Install from Git tag (pre-PyPI or bleeding edge)

For development or when testing unreleased patches:

```bash
pip install "git+https://github.com/SandRiseStudio/amprealize.git@v0.1.0"
```

### 4. Git submodule / subtree (not recommended)

Using a submodule pins to a commit SHA but adds merge friction and
CI complexity.  The version-pin-file approach achieves the same
reproducibility with less overhead.  Submodules may be reconsidered
if the two repos need to share non-Python assets (schemas, protos,
etc.) that aren't published as packages.

---

## CI Validation

OSS CI runs two version checks automatically:

| Job | Check | Flag |
|-----|-------|------|
| `packaging-smoke` | Built wheel matches `.amprealize-version` **exactly** | `--strict` |
| `test-python` | Editable install is compatible with `.amprealize-version` | (default — `~=` range) |

### Enterprise CI template

```yaml
# .github/workflows/ci.yml (enterprise repo)
- name: Install OSS dependency at pinned version
  run: |
    OSS_VERSION=$(cat .amprealize-version)
    pip install "amprealize==${OSS_VERSION}"

- name: Install enterprise package
  run: pip install -e ".[dev]"

- name: Validate version coupling
  run: python -c "
    from importlib.metadata import version
    oss = version('amprealize')
    ent = version('amprealize-enterprise')
    print(f'amprealize=={oss}  amprealize-enterprise=={ent}')
  "
```

---

## Release Workflow

When cutting a new OSS release:

1. Bump version in `pyproject.toml`.
2. Update `.amprealize-version` to match.
3. Tag: `git tag v<VERSION>` and push.
4. CI publishes to PyPI and npm automatically.
5. Enterprise repo updates **its** `.amprealize-version` and
   `pyproject.toml` dependency to the new version.

When cutting a new enterprise release:

1. Ensure `.amprealize-version` matches the required OSS version.
2. Bump `amprealize-enterprise` version in its own `pyproject.toml`.
3. Enterprise CI validates the coupling before publishing.

---

## Version Compatibility Matrix

| OSS Version | Enterprise Version | Status |
|-------------|-------------------|--------|
| 0.1.x | 0.1.x | Current — compatible release range |

Update this table as new minor versions ship.

---

## Quick Reference

| Question | Answer |
|----------|--------|
| Where is the version pinned? | `.amprealize-version` |
| What range does enterprise accept? | `~=0.1.0` (>=0.1.0, <0.2.0) |
| How does CI validate? | `scripts/check_oss_version.py` |
| Strictest install? | `pip install amprealize==$(cat .amprealize-version)` |
| Can I use a Git SHA? | Yes: `pip install git+https://...@<sha>` |
