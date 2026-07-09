# Project instructions

## Pull requests: single-commit, maintained in place

Every PR in this repository is kept to **exactly one commit**, and that commit is **maintained in
place** as the work evolves — do not stack follow-up commits.

- **Creating a PR:** branch, make the change as a single commit, push, open the PR.
- **Updating an existing PR** (new changes, review feedback, fixes): **amend** the existing commit
  (`git commit --amend`) and **force-push** to the PR's branch (`git push --force-with-lease`). Never
  add a second commit to a PR branch.
- Keep the commit message current: when amending, update the message so it still describes the whole
  change, not just the latest edit.
- Prefer `--force-with-lease` over `--force` so a force-push fails rather than clobbering unseen
  remote work.
- Open a PR for every change. One PR per branch: if the branch has no PR yet, open one; if a PR for
  the branch already exists, update it in place (amend + force-push) rather than opening a new one.
- If the PR for a branch has already been **merged**, treat follow-up work as a fresh change: restart
  the branch from the latest default branch and open a new PR — never reuse merged history.
