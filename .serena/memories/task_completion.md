# Task Completion Protocol

When a task is completed, the following steps should be taken:

1.  **Validation**: Run relevant tests (`pytest`, `npm test`, etc.) to ensure no regressions.
2.  **Documentation**:
    -   Update `BUILD_TIMELINE.md` with a new entry describing the change and verification steps.
    -   Update `PROGRESS_TRACKER.md` if the task relates to a tracked item.
    -   Update `WORK_STRUCTURE.md` if applicable.
    -   Update `PRD.md` or other design docs if contracts changed.
3.  **Compliance**:
    -   Check `AGENTS.md` for compliance.
    -   Ensure no secrets were leaked.
4.  **Final Report**: Summarize the changes, validation results, and files modified for the user.
