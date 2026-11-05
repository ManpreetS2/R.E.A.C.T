# Evidence backup procedure (copy-only; Mission 017)

Historical evidence lives in the gitignored `runs/` directory and is **not on GitHub**. This procedure only reads it. The tool is `src/rewardbench/evidence_backup.py`; it never writes into `runs/`, never overwrites a file and refuses to write its output inside `runs/`.

## State on this PC (2026-11-05)

* `runs/` in `C:\Users\sh1ft\R.E.A.C.T`: 1,848 files, 189,656,127 bytes.
* `docs/assets/research-results/MANIFEST.json`: 383 of 383 artifacts present and hash-identical (re-run today by `evidence_backup verify`).
* Local zip snapshots (same PC, not off-machine): `C:\Users\sh1ft\R.E.A.C.T-backups\react-runs-pre-mission012-2026-10-26.zip`, `react-runs-post-mission012-2026-10-27.zip`, `react-blind-visual-mission013-2026-10-27.zip`.
* Inventory of every file under `runs/` (path, bytes, SHA-256): `C:\Users\sh1ft\R.E.A.C.T-backups\runs-inventory-2026-11-05.json` (SHA-256 of that inventory file: `E9F8CBBBBF0D220DB1F1923BA72F1B3476E94452AC82CC44035C4AF785BB2D27`). The inventory is not committed because it lists private session paths; it contains no session data.
* **Not on this PC:** Mission 014 macOS and Mission 015A/015B session records, if any were produced on the owner's MacBook. They must be backed up from there.

## Steps for an off-machine copy (owner chooses the destination; this repository uploads nothing)

1. Verify the source first:
   `python -m rewardbench.evidence_backup verify --root C:\Users\sh1ft\R.E.A.C.T` → expect `complete: true`.
2. Create the inventory (skip if the file above is still current for the data you are copying; re-run after any new session):
   `python -m rewardbench.evidence_backup prepare --root C:\Users\sh1ft\R.E.A.C.T --out <new-file-outside-runs>`
3. Copy `runs\` (the directory, as a whole or as a zip of it) **and** the inventory to the private destination (external drive or private cloud you control). Do not put it in a public place and do not commit it.
4. On the destination, extract into an **empty new folder** so that it contains `runs\...`, then:
   `python -m rewardbench.evidence_backup check-copy --inventory <inventory.json> --copy <that-folder>`
   Expect `complete: true` and no `missing`, `mismatched` or `extra` entries.
5. Keep the source until the copy is verified. Repeat the check after every later copy.

The three zips above are same-machine snapshots only; they do not satisfy the off-machine requirement.
