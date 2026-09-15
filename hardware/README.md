# hardware

Altium projects and, later, mechanical CAD. The board this exists for is the
combined PDB + Teensy carrier specified in
[`../docs/POWER_ARCHITECTURE.md`](../docs/POWER_ARCHITECTURE.md) — that document
is the design intent; this directory is the implementation.

```
hardware/
├── arm-pdb/                  the PDB + Teensy board
│   ├── arm-pdb.PrjPcb        project file (text, diffable)
│   ├── *.SchDoc              schematic sheets (binary, LFS)
│   ├── *.PcbDoc              board (binary, LFS)
│   ├── libraries/            project-local symbols and footprints
│   └── outputs/              Altium output jobs write here — GITIGNORED
└── releases/                 what was actually sent to a fab — TRACKED
```

---

## The one rule that matters

**`.SchDoc` and `.PcbDoc` are binary. Git cannot merge them.**

Two people editing the same schematic on different branches does not produce a
conflict you can resolve — it produces a choice between one person's work and
the other's. There is no middle.

So:

- **One person edits a given document at a time.** Say so out loud before you
  start.
- **Never merge a branch that touched the same `.SchDoc` or `.PcbDoc`** as
  another branch. If it happens, pick a side deliberately with
  `git checkout --ours/--theirs` and redo the other side's work by hand.
- Prefer working directly on `main` for board work, or short branches that
  merge back the same day.

This is not a git limitation to route around; it is what binary CAD means. SVN
and Perforce solve it with exclusive file locks, which git does not have.

---

## Git LFS

The binary Altium files are tracked with LFS (patterns live in the repo-root
`.gitattributes`). They are rewritten whole on every save, so plain git would
store a full copy per commit and the repo would grow by megabytes a day.

**On a fresh clone, once per machine:**

```bash
git lfs install
git clone https://github.com/ssougu/6-DOF-ARM-PROJECT.git
```

If you clone without LFS installed, the Altium files arrive as small text
pointer files and Altium will refuse to open them. The fix is
`git lfs install && git lfs pull` — nothing is lost.

GitHub's free tier is 1 GB of LFS storage and 1 GB/month of bandwidth. That is
comfortable for one board; keep an eye on it if the mechanical CAD lands here
too.

---

## What is tracked, and what is not

**Tracked:** `.PrjPcb`, all `.SchDoc` / `.PcbDoc`, project-local libraries,
`.OutJob`, and anything under `releases/`.

**Ignored:** `History/`, `__Previews/`, `Project Outputs for */`, previews,
autosaves, `*.DsnWrk`. See `.gitignore` — the list is not exhaustive and should
grow as Altium shows you what else it makes.

`History/` matters most. Altium keeps its own copy of every save there and it
reaches gigabytes on an active project. Git is the history; that folder is not.

**Libraries live inside the project.** If a symbol or footprint comes from a
path outside this repo, the project does not open correctly on another machine
and is not reproducible six months from now. Keep them in `libraries/` and
reference them relatively.

---

## Releases — what you actually sent to a fab

Working outputs are ignored because they are regenerated constantly. But "which
files did we send?" is a real question with a real cost when the answer is
wrong, so the ones that leave the building get kept:

```
hardware/releases/
└── arm-pdb-revA-2026-10-xx/
    ├── gerbers.zip
    ├── bom.csv
    ├── pnp.csv
    └── NOTES.md        what changed, what was ordered, from whom
```

And tag the commit:

```bash
git tag -a pcb-arm-pdb-revA -m "Sent to <fab> on <date>"
git push origin pcb-arm-pdb-revA
```

The tag is what lets you get back to the exact source that produced a board you
are holding — including when the board turns out to be wrong.

---

## Working habits

**Close Altium, or at least save everything, before committing.** Altium holds
file handles and writes lazily; committing mid-edit can capture a half-written
binary that opens with errors.

**Commit at logical points, not on every save.** Each `.PcbDoc` commit is a
full new copy in LFS. "Placed all connectors", "routed 36 V distribution",
"passed DRC" are commits. Autosaves are not.

**Write what changed in the message.** You get no useful diff on these files,
so the commit message is the only record of what a revision actually did. This
matters more here than anywhere else in the repo.

**Run DRC before committing a `.PcbDoc`** and say so in the message. A commit
that is known-clean is worth far more than one that might be.

Altium can drive git directly (Preferences → Data Management → Version Control),
but the CLI works fine and gives better commit messages.

---

## Before the first commit of real work

From `POWER_ARCHITECTURE.md` §6 — worth having set before the board exists
rather than retrofitting:

- IPC footprint density **Level A (Most)** for hand assembly
- **Thermal relief spokes on every through-hole pad landing on a 2 oz pour**,
  set in the footprints now — without them the joints will not flow
- Nothing finer than SOIC / SOT-23, passives at 0805
- Confirm the fab's minimum trace/space for 2 oz outer copper before setting
  design rules; heavy copper typically needs 6–8 mil rather than 4–5
