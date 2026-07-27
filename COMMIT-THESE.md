# Round 5: job boards, README, and one honesty bug

## Commit everything

```powershell
cd B:\omnigab\omnigab

git add -A
git commit -m "add extraction schema and mechanical verification gate for bills"
git push origin main
```

That `git add -A` also clears the two scratch files from last round, since deleting them locally did not untrack them.

Then, so the history stays readable, the rest as separate commits:

```powershell
git add src/jobs/ src/tools/job_boards.py src/tools/__init__.py
git commit -m "add multi-board job search with api sources and browser handoff"

git add src/core/job_renderer.py
git commit -m "make the result renderer source-aware and stop claiming unverified links were checked"

git add README.md
git commit -m "rewrite readme around what the tool is and why"

git push origin main
```

---

## On LinkedIn, Indeed, Handshake, and Amazon

You asked for four scrapers. I built two of them properly and deliberately did not build the other two. Here is the reasoning, because it changes what your tool is rather than just how it is implemented.

Job boards fall into three groups:

| Access | Boards | Reality |
| --- | --- | --- |
| Public API | USAJOBS, **Amazon Jobs**, **RemoteOK**, **Greenhouse**, **Lever** | Documented JSON endpoints. Fast, stable, allowed. |
| Scrape | Indeed | No API. Needs a real browser, throws Cloudflare challenges constantly. |
| Prohibited | **LinkedIn**, **Handshake** | Terms forbid automated access and it is actively enforced. |

I tested every API above against the live endpoints before writing a line of code. Amazon Jobs returned 264 matches for "information security"; Greenhouse returned 533 open roles on Stripe's board. Those work.

LinkedIn is the one worth being blunt about. Their terms prohibit automated access and they enforce it with account restrictions. Scraping LinkedIn to find jobs risks the LinkedIn account you are using to apply for jobs. That is a bad trade at any level of technical success, and it is not a trade I would make quietly on your behalf.

So LinkedIn, Handshake, and plain Indeed searching use **browser handoff**: omnigab builds the exact search URL and opens it in your own browser, where you are already logged in. You get the same results, your account stays safe, and there is nothing to break the next time they change their markup.

This is a better design, not a consolation prize. It is also an honest thing to say in an interview: "I chose not to scrape LinkedIn because their terms prohibit it and enforcement targets the user's own account, so I built a handoff instead."

Indeed Easy Apply still works through the existing Playwright tool. That is you driving your own logged-in browser, which is a different thing from scraping their search results at scale.

---

## What I built

**`src/jobs/sources.py`** — a source registry. Every board declares how it is accessed (`api`, `scrape`, or `handoff`) and normalizes to one posting shape. Adding a board is now a small class, not a new scraper.

Implemented: `AmazonJobs`, `RemoteOK`, `GreenhouseBoard` (any company token), `LeverBoard` (any company token), and handoff entries for LinkedIn, Handshake, and Indeed.

The Greenhouse and Lever ones are worth knowing about. Thousands of companies host their careers pages there, so `greenhouse_company: "stripe"` searches Stripe's real board through a documented API. That covers a large slice of tech hiring with no scraping at all.

**`src/tools/job_boards.py`** — the agent-facing tool, registered in `src/tools/__init__.py`. One source failing never fails the whole search; it collects errors and returns partial results, because boards go down.

**Renderer fixes.** Plugging in new sources exposed three bugs in `job_renderer.py`:

1. Every link said "Apply on USAJOBS", including Amazon ones.
2. Every posting printed "Series ?" — a federal concept that is noise elsewhere.
3. Every result claimed *"Every link above returned HTTP 200 when checked."*

That third one is the one that actually mattered. `usajobs_search` really does fetch every URL and discard dead ones. The public board APIs do not. So the renderer was making a verification claim the data had not earned, which is the same class of problem as the invented links I fixed earlier, just from the other direction. It now only makes that claim when the payload proves it.

Handoff links now render in the results too, under a line explaining why they are links rather than listings.

---

## README

Rewritten around what the tool is and why it exists, rather than a feature list. The lead is the actual argument: your lease and your medical bills are exactly the documents an assistant would be most useful for and exactly the ones you should be least willing to upload, and running the model locally turns privacy from a promise into a property of the architecture.

Also added: an honest job board access table, the context window guidance including the q8_0 KV cache math, a concrete privacy table showing where each kind of data physically lives, and a section on the extraction gate.

One thing I made explicit rather than hiding: the `tools: broken` header on small models. It now says plainly that 1.5B cannot use tools reliably and 7B is the first size that can. Users will hit that regardless, and finding it documented reads as competence rather than a bug.

---

## Still not done

The ASVAB GUI. You said ugly, clunky, weak questions, and all I have shipped there is the answer-position fix. It is untouched otherwise.

Tests: 24/24 on the main suite, 20/20 on the gate.
