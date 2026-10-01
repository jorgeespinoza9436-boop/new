# Merged agents (top.py shell)

Upgraded copies of `../harnyx-agents-17-2026-09-13T03-50-45` wrapped like
`../top.py`.

## What changed

Each source pack was a BUILDJ 3/4-body rotate with a weak outer shell
(sequential try, captured-text floor, no gateway failover, no host pairwise
judge). The builder:

1. Extracts the research factories
2. Maps them to A/B/C/D from the source route
3. Wraps them in the top.py shell (gateway failover, concurrent pair race,
   schema clamp/floor, host pairwise judge)

Three-factory packs alias D to A, same as `agentv3.py`.

## Output

| | |
|---|---|
| Dir | `/root/new1/new/merged/` |
| Files | 17 agents + `build_top_wrap.py` + `manifest.json` + this README |
| Factories | 12 with 4 distinct bodies, 5 with 3 (D aliases A) |
| Size | 535–667 KB (all under 1 MB) |
| Entrypoint | Identical to `top.py` (`_r4_dispatch` → `_r5_select` / `_r4_floor`) |

Slot identities (from each source route):

| UID | A | B | C | D |
|---|---|---|---|---|
| 6 | v52 + c7-422 | v52 | ours-v24 | v240-4-phzu |
| 14 | v52 + c3-405 | v52 + w5 | grid-v4 | =A |
| 27 | v52 + p2-406 | v52 + w5 | ours-v16 | staged |
| 56 | v52 + c5-403 | v52 | ours-v22 | staged |
| 68 | v52 + c4-420 | v52 | ours-v19 | staged |
| 80 | v52 + c5-406 | v52 + w5 | ours-v16 | staged |
| 83 | v52 + c5-406 | v52 | rubric-v2 | staged |
| 90 | v52 + c4-416 | v52 + w5 | ours-v14 | v230-2-fdlq |
| 101 | v52 + c3-402 | v52 | ours-v16 | staged |
| 105 | v52 + f2e-423 | v52 + w5 | ours-v24 | =A |
| 132 | v52 + c5-421 | v52 | ours-v14 | v260-15-rhsc |
| 167 | v53-claim-board | v52 | ours-v16 | v270-7-svac |
| 173 | v52 + c4-410 | v52 | grid-v6 | =A |
| 206 | v52 + c3-402 | v52 + w5 | ours-v22 | =A |
| 215 | v52 + c3-401 | v52 + w5 | grid-v6 | =A |
| 242 | v52 + c4-415 | v52 | grid-v6 | staged |
| 244 | v52 + c4-410 | v52 | grid-v2 | staged |

## Rebuild

```bash
python3 /root/new1/new/merged/build_top_wrap.py
```
