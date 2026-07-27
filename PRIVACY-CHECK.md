# Privacy audit of the omnigab repo

Answers to your questions, plus one thing I found that still needs fixing.

## 1. Is your information leaking now?

No. `data/storage.db` and `data/kev_catalog.json` are untracked and gitignored. Nothing you type into the app from here on reaches GitHub.

## 2. What about previous versions? (the right question to ask)

You were right to ask. `git rm --cached` only stops future tracking. Old commits keep their copy of the file forever, and anyone can read it with `git show`. So I checked every version instead of assuming.

`data/storage.db` was committed in three places. I extracted each version and opened it as a database:

| Commit | facts | sessions | application_history |
| --- | --- | --- | --- |
| `033f414` | 0 rows | 0 rows | 0 rows |
| `d98cf15` | 0 rows | 0 rows | 0 rows |
| `e169241` | removed | removed | removed |

One wrinkle worth knowing: the tables were empty, but SQLite's autoincrement counter read 6 and 7, meaning rows had been inserted and later deleted. Deleting a row in SQLite does not necessarily erase its bytes, so I also scanned the raw file for recoverable text. Both versions contain only schema definitions. No names, no locations, no job history, nothing recoverable.

**Verdict: the database in your history is clean.** No action needed.

## 3. What I did find: resume drafts are still tracked

These are live on GitHub right now:

```
data/resume_drafts/20260526_180712_supervisory_it_cybersecurity_specialist_plcypln_in.json
data/resume_drafts/20260526_180712_supervisory_it_cybersecurity_specialist_plcypln_in.md
```

They contain a generated federal resume: work history (UMD ResNet volunteer), education (University of Maryland coursework), home lab details, and skills with durations.

I scanned both for contact information and found none. No name, no email, no phone, no address. So this is career history, not identity theft material. Still, it is generated output from running the app, which by the rule from earlier means it does not belong in the repo.

Fix below.

## 4. Your email address is in your commit history

Worth knowing since you chose to keep the account pseudonymous:

- 30 commits authored as `cooperpreston43@gmail.com`
- 8 commits authored as `145511592+duckcoop@users.noreply.github.com`

Commit metadata is public. Anyone running `git log` on your repo sees the real address on those 30 commits.

Going forward this is a thirty second fix (step 3). Rewriting the 30 existing commits is possible but disruptive: it changes every commit hash, and anyone who cloned the repo gets conflicts. Given that a personal gmail is fairly low harm and you are actively job hunting anyway, my honest read is fix it going forward and leave the history alone. Your call though, and I can walk you through `git filter-repo` if you want it gone.

---

# The fixes

Run from `B:\omnigab\omnigab`.

## Step 1: untrack the resume drafts

Removes them from git, keeps your local copies.

```powershell
git rm --cached data/resume_drafts/20260526_180712_supervisory_it_cybersecurity_specialist_plcypln_in.json
git rm --cached data/resume_drafts/20260526_180712_supervisory_it_cybersecurity_specialist_plcypln_in.md
```

## Step 2: ignore the whole folder so this cannot recur

I already added the rule to `.gitignore`. Commit it:

```powershell
git add .gitignore
git commit -m "stop tracking generated resume drafts"
git push origin main
```

## Step 3: use GitHub's private email for future commits

```powershell
git config user.email "145511592+duckcoop@users.noreply.github.com"
```

That is your real GitHub noreply address, so commits still link to your account and still count toward your contribution graph. To apply it everywhere instead of just this repo, add `--global`.

Also turn on the setting that stops this happening again:
GitHub → Settings → Emails → check **Keep my email addresses private** and **Block command line pushes that expose my email**.

Verify it took:

```powershell
git config user.email
```

---

## 5. Your venv question: you were right

> I didn't want to run the setup because I didn't know how to commit without the venv folder being there, as it's personal to your PC

Correct on both counts, and it is good instinct.

A virtual environment is machine-specific. `pyvenv.cfg` hardcodes the absolute path to the Python that built it, and the `Scripts/` executables embed that path too. Copying one between machines, or even renaming its parent folder, breaks it. That is exactly why renaming `omnigab#` to `omnigab` would have broken any venv that had been there.

The correct pattern is the one this repo already uses: commit `requirements.txt`, ignore `venv/`. Anyone who clones runs setup and builds their own. `venv/` and `.venv/` are already in `.gitignore` at lines 38 and 39, so it was never going to be committed.

So running setup was always safe. Nothing it creates gets tracked.

**The general rule, again:** if a file is produced by *running* the program, ignore it. If it is produced by *writing* the program, commit it. `requirements.txt` you wrote. `venv/`, `storage.db`, and the resume drafts were all produced by running things.
