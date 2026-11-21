# Traps of the tools

Each line is something a tool did on the day named, in the Claude desktop app's Code tab on Windows. A trap is a guess that the tool still behaves that way: try it again before relying on a line that is months old, and delete the line when it no longer happens.

| Seen | What happens | What to do |
|---|---|---|
| 2026-11 | A new session's worktree starts from the repository's default branch, and a proposed card drops the branch it was given. | Name the base branch in the brief. |
| 2026-11 | A turn that an event opened may refuse to start a session. | Try; when refused, propose the session as a card, or start it in a turn the user opened. |
| 2026-11 | A message to a working session only queues; it runs when that session's turn ends. | To halt a session now, stop it; do not send "stop". |
| 2026-11 | A session's closing report is longer than the short note the orchestrator receives. | Read the session's last message before judging its work. |
| 2026-11 | A shell `cd` into a worktree moves the session's primary folder there. | Use `git -C` and absolute paths. |
| 2026-11 | Syncing a session with its base is refused when the base changed a file under `.claude/`. | Fetch and merge inside the worktree. |
| 2026-11 | Auto-fix on a pull request forbids rebase and force-push. | A session syncs its branch by a merge commit; read hand resolutions with `git show --remerge-diff`. |
| 2026-11 | A draft pull request runs no checks, and marking it ready in the same second as a push leaves one run skipped and one cancelled. | Mark it ready, wait some ten seconds, then push. |
| 2026-11 | A stopped preview can leave its server running, which keeps the built binary locked. | Find the process by its path and stop that one process. |
| 2026-11 | Stopping a build tool by its image name stops every session's build. | Stop only the run you started. |
| 2026-10 | Worker sessions share one scratch folder; two that write the same file name overwrite each other. | Ask each worker to name scratch files after its piece. |
| 2026-10 | The usage limit stops every session at once. | They resume on a message; the app may now continue them by itself. |
