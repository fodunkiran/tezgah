# Reviewing a pull request

A fresh reviewer helps because it has not seen the author's reasoning. Handing the same task to another agent again does not improve the answer; reading the result with new eyes does.

## The reviewer

- **A new, read-only agent for each round.** A resumed reviewer pays for its whole context again on every turn, and by a late round that context is most of the cost.
- **Its model is named in the call.** The user's own rules say which models may be used.
- **It gets** the diff or the pull request to read, the brief's "done when" list, and, from the second round on, the earlier findings as a short list with what was done about each.
- **It does not get** your conclusion.

A reviewer that has to build or run something builds into its own worktree's target folder. A build folder shared between checkouts can run another checkout's binary.

## What it returns

A short verdict, not a transcript:

- **Blockers.** Defects that make the change wrong or unsafe. Each names the file and line, the input or state that shows it, and what goes wrong.
- **Other findings.** Worth fixing, not blocking.
- **Checked and fine.** The "done when" items it verified, and how.
- **Not checked.** What it could not verify.

## Rounds

Review, fix in the author's own session, re-check: two rounds. A third only when the re-check confirms a blocker. A reviewer asked again will find something again; stop when the blockers are gone.

## Reading a review

- **A rule the reviewer proposes is a change like any other.** Measure it before adopting it.
- **A claim about what a document or a decision record says** is checked against that record.
- **A remark on wording in the user's language** is read by you before it reaches the author.
- **Before the last round on a feature another part of the system judges,** try it on real inputs. Ask what a hostile input costs in memory as well as in time.
