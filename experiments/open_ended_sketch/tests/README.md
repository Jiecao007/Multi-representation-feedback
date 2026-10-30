# Runtime checks

The running three-agent architecture is tested by:

- `test_three_agent_runtime.py`: call boundaries, sparse memory, formal ownership, edits, image roles, legacy-session migration and transaction behavior.
- `test_learner_model.py`: formal results, important observations, versions and representation references.
- `test_tutor_context.py`: compact graph evidence and bounded short-term dialogue.
- `run_three_agent_browser.py` / `test_three_agent_browser.mjs`: a real local HTTP/browser workflow with typed model stubs and isolated output. It creates an arrow with Connect, submits it and saves JSON/HTML.

`legacy_support/` preserves the pre-refactor feedback implementation and its prompts for historical regression checks. Fixtures exported by `test_feedback.py`, and the explicitly historical policy tests using those fixtures, run against that archive. The live application does not import it. Geometry, upload, HTTP, case-recovery and export checks also remain useful independently of instructional routing.

Run the complete Python suite from the project root:

```bash
python3 -B -m unittest discover -s experiments/open_ended_sketch/tests -p 'test_*.py' -v
```

Tests use local model stubs. A passing offline or browser test does not demonstrate model teaching quality or live response speed. Historical browser scripts can contain dated output paths; use the new isolated three-agent QA script when checking the current workflow.
