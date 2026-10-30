# Project context: simulated learners

For work related to simulated students/learners, first read
[SIMULATED_LEARNERS.md](experiments/open_ended_sketch/simulated_students/SIMULATED_LEARNERS.md).
It is the project handoff for implementation, profiles, API input/output, actions,
evidence, latest exports and unresolved research questions. Update it after relevant
changes or experiments; keep historical outputs unchanged.

Status recorded 2026-10-21: browser-based P1/P2 trials and existing-system exports
are complete. P2's low-motivation distinction remains unvalidated. The latest
closure-routing correction was applied after exports and has not had another
live trial. Consult the handoff and experiment snapshots before treating current
code as the version used in those exports.

Later the same day, student inputs were deduplicated and student_prompt.md was
shortened (45% fewer words). History now carries lossless memory_delta patches
plus the latest full memory. Projection version is deduplicated-v1. All 46 offline
tests passed; replaying 31 saved inputs reduced prompt+JSON characters by about
27%. No live trial or measured token/billing result exists for this revision.
See handoff section 17 and analysis/input_compaction_20261021.json.
