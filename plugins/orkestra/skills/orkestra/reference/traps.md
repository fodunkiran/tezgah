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
| 2026-11 | An app restart cuts subagents off mid-run; they keep their context. | Resume each with a message to its id; do not start it again. |
| 2026-11 | `archive_session` and `stop_session` in auto mode come back once with "no verdict": a hook adds a `session` label to the input after the review. | Send the call again with exactly the input the refusal quotes, alone in its message. |
| 2026-11 | `archive_session` refuses a session that still runs a background task, such as a page server, as "live work". | Ask the session to stop what it started, then archive it. |
| 2026-11 | `->` in a session title comes out mangled. | Keep titles to plain words. |
| 2026-11 | Sessions leave their hand-over notes in the app's own folder, `%APPDATA%\Claude\side-session-notes\<orchestrator session id>\`. | Read it when a report names a note. |
| 2026-11 | The auto-mode classifier refuses a merge that the session's own chat did not authorize, and a branch deletion with `git push --delete`. | Get the user's word in the chat before the first merge; leave merged branches to the repository's own deletion. |
| 2026-11 | A job on GitHub's runners that fails in about two seconds with no steps was stopped by billing, not by the code. | Run the checks locally until the user fixes billing. |
| 2026-11 | A self-hosted runner started in a terminal tab stops when its session or the app restarts: jobs sit queued, and one cut off mid-run fails with no log. | Start the runner again and re-run the failed job. |
| 2026-11 | A self-hosted runner on the working machine fails tests a pull request never touched while sessions build or loop tests. | Read which tests failed; re-run once the machine is quiet. |
| 2026-10 | Worker sessions share one scratch folder; two that write the same file name overwrite each other. | Ask each worker to name scratch files after its piece. |
| 2026-10 | The usage limit stops every session at once. | They resume on a message; the app may now continue them by itself. |
| 2026-10 | A new session can sit on a permission prompt seconds after it starts. | Look at the sessions' state soon after starting several; resume a stalled one with a message. |
| 2026-10 | `gh pr merge --delete-branch` on a stack's lower step closed the pull request stacked on it, and it could not be reopened. | Merge lower steps without `--delete-branch`; rebase a closed follower with `git rebase --onto origin/<integration> <old base>` and open a new pull request. |
| 2026-10 | `git worktree remove` on Windows can fail with "Permission denied" and leave an empty folder. | The branch can still be deleted; leave the folder to the app. |
