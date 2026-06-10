---
name: amprealize-parity-check
description: Align CLI, API, and MCP behavior when adding or changing Amprealize features. Use when touching surfaces that should stay consistent across tools.
---

# Cross-surface parity

1. Identify which surfaces are affected (CLI, REST, MCP, web).
2. Map to existing contracts under `docs/contracts/` and shared Pydantic models where the codebase uses them.
3. Extend or add parity tests in `tests/test_*_parity.py` patterns when the repo already tests parity that way.
4. Update capability matrix or client docs if behavior or availability changes.

See **`behavior_validate_cross_surface_parity`** in [AGENTS.md](https://github.com/SandRiseStudio/amprealize/blob/main/AGENTS.md).
