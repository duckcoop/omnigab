# Round 4: repo cleanup

First, the privacy fix worked. Your screenshot:

> **You:** is this all public?
> **omnigab:** No, nothing typed here is uploaded anywhere. The documents you add in the Docs tab are indexed into a vector store on your machine and never leave it... they remain private to your device.

That is the correct answer, and it is the one your product depends on being correct.

---

## The folder looks messier than the repo actually is

Worth separating these two things, because they need different fixes.

Your Explorer window shows 28 items. A person who clones your repo sees 14 files in the root. The difference is runtime junk that only exists on your disk and is already gitignored:

| On your disk only | What it is |
| --- | --- |
| `venv/` | your virtual environment |
| `models/` | 9 GB of downloaded weights |
| `data/`, `logs/`, `vectorstore/` | generated state and indexes |
| `__pycache__/` | compiled bytecode |
| `.env` | your API token, correctly untracked, I checked |

None of that reaches GitHub. It just makes your local folder look busy. That part is normal and fine.

What genuinely was cluttered is the tracked root, and that I have cleaned.

---

## What I changed

**Moved into `docs/`:** `SETUP_GUIDE.md`, `SKILL_LEARNING_PROMPT.md`, `TODOS.md`. Nothing linked to them, so nothing broke.

**Deleted the 4 fake test docs.** Nothing in the code, README, or tests referenced them. I verified before touching them.

**Cut down to one entry point,** as you chose. `launcher.py` and `start.bat` go. `setup.bat` already launches `desktop_app.py` directly and `omnigab.bat` does too, so nothing depended on either file. Note this also removes the browser UI launcher and `--terminal` mode. The FastAPI server still runs (the desktop app talks to it), so `http://localhost:8080` still works if you type it. You just do not advertise it.

**Added `data/docs/.gitkeep`** so a fresh clone still has the folder, with a note inside explaining what goes there. Git does not track empty directories, so without this a new user clones and the folder is simply missing.

**Improved the empty-index message.** With no documents, `rag_search` returned a bare "No documents indexed." Now it tells the model to explain that files can be added in the Docs tab or dropped in `data/docs`, and that they stay on the machine. New users hit this state on their very first question.

**Updated the README** to match: launch instructions now say `omnigab.bat` and nothing else, and the structure diagram reflects the new layout.

Root goes from 14 tracked files to 9:

```
.flake8  .gitattributes  .gitignore  LICENSE  README.md
desktop_app.py  omnigab.bat  requirements.txt  setup.bat
```

---

## Commit it

The `rm` calls failed from my side because the B: drive blocks deletes, so `git rm` below does the actual deleting. That is also the correct way to do it, since it stages the removal at the same time.

```powershell
cd B:\omnigab\omnigab

git rm launcher.py start.bat
git rm data/docs/active_directory_guide.md data/docs/network_infrastructure.md data/docs/vpn_setup.md data/docs/workstation_setup.md
git add -A
git commit -m "cut to a single entry point, move guides into docs, drop test fixtures"

git add src/tools/rag_search.py
git commit -m "explain how to add documents when the index is empty"

git push origin main
```

`git add -A` picks up the moves into `docs/` as renames, so the history stays readable.

Afterwards, check it looks right:

```powershell
git ls-files | Select-String -NotMatch "/"
```

Should list exactly the 9 files above.

---

## Still outstanding from earlier rounds

If you have not run these yet, they are the two that matter most:

```powershell
git rm --cached data/resume_drafts/20260526_180712_supervisory_it_cybersecurity_specialist_plcypln_in.json
git rm --cached data/resume_drafts/20260526_180712_supervisory_it_cybersecurity_specialist_plcypln_in.md
git add .gitignore
git commit -m "stop tracking generated resume drafts"

git config user.email "145511592+duckcoop@users.noreply.github.com"
```

The first removes your work history from the public repo. The second stops future commits carrying your real email. Background in `PRIVACY-CHECK.md`.

Delete the two scratch files when you are done with them:

```powershell
Remove-Item COMMIT-THESE.md, PRIVACY-CHECK.md
```

Tests: 24 passed, 0 failed, verified against a copy with the deletions applied.
