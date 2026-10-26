# Paid experiment evidence: manifest (as of 2026-10-26)

Two single-call exploratory attempts with `openai:gpt-5.4-mini`, `no_feedback` arm, development seeds 0-7.
**Total paid spend: $0.003516** (OpenAI project limit $0.25, prepaid credit $5, auto-reload off).
Machine-readable version with per-file SHA-256: `MANIFEST.json` (same directory).

| Mission | Prompt | Experiment id | Calls | Tokens | Cost (USD) | Outcome |
| --- | --- | --- | ---: | ---: | ---: | --- |
| 006 | `rewardbench.prompts.v2` | `exp_26eb2593d31e4a72c041` | 1 | 1,220 | 0.00258375 | Schema document echoed back; invalid (`unknown controller policy None`); nothing flown |
| 008 | `rewardbench.prompts.v3` | `exp_bcc1e26372179700a53d` | 1 | 1,073 | 0.00093225 | Valid, but a verbatim copy of the prompt's format example (`constant`, thrust 0.5, rotation 0); 8/8 timeouts at 8000 steps, mean reward -104.56 (range -106.01 to -102.67), 0 landings, 0 crashes |

Both are exploratory engineering attempts, not study data. Neither is a learning result (one revision each; the
session paused by design after one paid call). They are excluded from every later analysis and their spend counts
toward every later ceiling. Configs that produced them are archived byte-for-byte in
`configs/study/archive/prompt_v2/` and `prompt_v3/`.

## Where the artifacts are

`runs/` is gitignored, so **none of the raw artifacts below are on GitHub**. Only this manifest, the archived
configs and the protocol text are.

| Local directory | Contents | Size |
| --- | --- | ---: |
| `runs/first-llm-study/pilot/` (Mission 006) | SQLite database, run and report logs, 2 prompt logs, report.md and 6 PNG charts | ~0.4 MB |
| `runs/first-llm-study/pilot-p3/` (Mission 008) | SQLite database, run and report logs, 2 prompt logs, report.md and 6 PNG charts, **8 flight recordings** (`flights/exp_bcc1e26372179700a53d/*.flight.json`, ~465 KB each) | ~4.3 MB |

Verify a restored copy with `sha256sum` against `MANIFEST.json`. The databases contain the raw model replies,
prompts, token counts and costs. Neither database, prompt log nor run log stores an API key (the key is read
from the environment and never persisted), but review before sharing outside the private repo.

## Backing up the local-only artifacts (needs owner approval)

Nothing was uploaded. Options, smallest risk first:

1. **Private release asset or private repo** holding one archive of the two directories (~5 MB):
   `Compress-Archive -Path runs\first-llm-study\pilot,runs\first-llm-study\pilot-p3 -DestinationPath react-evidence-2026-10-26.zip`,
   check it against `MANIFEST.json`, then attach it to a GitHub release on the private repo. Do not `git add -f` into `runs/`.
2. **Local copy** to an external drive or a cloud folder you control; same zip.
3. **Commit only the small text evidence** (prompt logs, run logs, report.md, about 30 KB) into a dated folder under
   `docs/assets/` if you want them diffable in git; leave the databases and flight JSON in the archive.

The repository is private; flight JSON and databases are small enough that option 1 is practical, but they are
raw data, so approve it explicitly first.
