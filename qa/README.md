# Validation harness

## Status: the prototype referenced by the project docs is not in this tree

`CLAUDE.md` carries the standing rule:

> **Do not modify the Python prototype in `qa/`.** It is the validation
> harness, not a deliverable.

and `PROJECT_PLAN.md` §3.2 relies on it:

> The existing Python prototype already produces plane count, tilt and mean
> height per plane; **keep it as the QA harness.** It is an independent
> estimate of how many roof planes a building should have.

No such prototype was present when this pipeline was built — the working
directory contained only the LAS tile, the footprint GeoPackage and the two
project documents. Nothing has been written here in its place, because
rewriting it is explicitly ruled out and a fresh implementation would not be
*independent* of the pipeline it is supposed to check.

**This blocks Phase 3.2 roof-plane recall**, and only that metric. It does not
affect Phase 1 or Phase 2. The other Phase 3 metrics — point-to-surface RMSE,
val3dity validity, volume/height error, runtime — do not depend on it.

To unblock, restore the prototype from wherever it currently lives (a previous
working directory, or version control) and drop it in here.

## What Phase 1 already produces

The prepare-tile stage writes an independent per-building record that covers
part of the same ground, in `out/qa/`:

| file | contents |
|---|---|
| `<tile>_qa.json` | machine-readable record for every stage: counts in, counts out, metrics, failures |
| `<tile>_qa.md` | the same record, readable |
| `<tile>_per_building.csv` | per footprint: failure reason, point counts, coverage, measured eave offset |

The failure reasons emitted are documented in `pipeline/diagnose.py`.
