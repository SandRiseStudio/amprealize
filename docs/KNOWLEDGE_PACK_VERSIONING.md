# Knowledge Pack Versioning Rules

> Applies to all packs managed by the Amprealize Knowledge Pack system.

## Semantic Versioning

Knowledge packs follow [Semantic Versioning 2.0.0](https://semver.org/) (`MAJOR.MINOR.PATCH`).

### MAJOR (breaking)

Increment when changes **require workspace re-activation or may alter agent behaviour in backwards-incompatible ways**:

- Removing or renaming overlay IDs referenced by active workspaces.
- Changing the meaning of existing constraint keys (e.g. `strict_role_declaration` semantics change).
- Removing behaviour refs that workspaces depend on.
- Restructuring doctrine fragments such that existing overlay selectors no longer match.

### MINOR (additive)

Increment when new capabilities are added **without breaking existing activations**:

- Adding new overlays (task, surface, or role).
- Adding new behaviour refs.
- Adding new sources.
- Adding new doctrine fragments.
- Introducing new constraint keys with safe defaults.

### PATCH (fix)

Increment for **non-functional corrections**:

- Fixing typos or clarifying wording in overlay instructions.
- Updating retrieval keywords.
- Correcting metadata (timestamps, creator info).
- Adjusting overlay priority values.

---

## Upgrade Policy

| Change level | Workspace behaviour |
|---|---|
| **Patch** | Auto-applied silently. Active workspaces use the latest patch of their pinned minor version. |
| **Minor** | Auto-applied with a single log line noting the upgrade. No user prompt required. |
| **Major** | Requires explicit user acceptance. `amprealize knowledge-pack upgrade` prompts for confirmation. Active workspaces continue using their pinned version until the user accepts. |

---

## Migration Rules

1. **Backwards compatibility window** — After a major release, the previous major version remains available for **30 days** to allow migration.
2. **Overlay ID stability** — Once an overlay ID is published in a minor release, it must not be removed until the next major.
3. **Constraint defaults** — New constraint keys introduced in minor releases must default to the least-restrictive value (typically `false` or `[]`).
4. **Source additions** — New sources added in minor releases must be marked `conditional: true` if they require files that may not exist in every workspace.
5. **Deprecation markers** — Overlays scheduled for removal in the next major must be annotated with `"deprecated": true` and `"deprecated_in": "<current_version>"` for at least one minor release before removal.

---

## Version Pinning

Workspaces pin to a **minor series** by default (e.g. `0.3.x`). This means:

- Patches auto-apply.
- Minor upgrades auto-apply.
- Major upgrades require explicit accept.

To pin to an exact version: `amprealize knowledge-pack pin --version 0.3.2`.

---

_Implements T1.1.3 (AMPREALIZE-297) of the Knowledge Pack Foundations epic._
