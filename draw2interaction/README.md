# Draw to Explore — feedback on student models

The submission screen collects the task (text, an optional task figure, or both),
student diagram, optional written explanation and optional learning requirements.
Start feedback opens the diagram on the left
and a compact conversation on the right, with the task above both.

The October 10 workflow follows Tables 1 and 2 in the design document. Initial
feedback recognizes supported strengths and invites reasoning. Dialogue uses
Press for accuracy for errors and Revoice or clarification for ambiguity.
The learner first judges the current diagram's evidence against the goal;
an accuracy check does not announce the diagnosis or ask how to repair it.
Ordinary confirmation follows a grounded learner conclusion about that same
issue. Explicit hints/revision requests permit direct help.
The Feedback thinking dialogue then selects among four moves to develop enough
understanding for a feasible revision. Direct hints teach the next action rather
than continuing a question loop. An explicit revision request in chat opens a
concrete plan without another readiness test. The **Begin a revision** button
unlocks editing directly without a preset message or an AI call.
Each discussion–revision–review cycle concerns one core issue. Several related
diagram elements can be revised together when they share the same underlying
problem. Editing starts locked and opens with **Begin a revision**, a chat
revision request, the system's Feed forward plan, or a Feedback guidance instruction
that actually asks the learner to modify the diagram. Explanation/observation hints
alone do not unlock editing. **Exit revision** closes editing and preserves the
unsubmitted draft, with no message or AI call. Review changes submits the actual
revision. A verified operational fix with previously established understanding
receives brief praise without another WHY. Conceptual changes need a relevant
reason only when it has not already been explained; missing reasoning keeps the
changes and receives one focused follow-up. Continue an unresolved
issue, or select the next independent issue after resolving the current one.
When no relevant issues remain, invite further questions.
See [WORKFLOW_1010.md](WORKFLOW_1010.md).

The prior **Mechanics Studio** feedback workflow has been integrated. See
[INTEGRATION.md](INTEGRATION.md) for its original location, source mappings and validation.

From the project root:

```sh
python3 -B experiments/open_ended_sketch/app/server.py
```

Open http://127.0.0.1:8765. On macOS, `start.command` starts the same service.
The configured root `.env` supplies `OPENAI_API_KEY` on the server only.
If dependencies are missing, install `experiments/open_ended_sketch/requirements.txt`.

The app lives in `experiments/open_ended_sketch/app/` so it shares the existing
independent API experiment's schema and versioned prompts. No hosting, login,
or frontend API key is required. This is a local research prototype.

## Student interactions

- Submit a PNG, JPEG, or WebP picture and optional task context.
- Attach a separate **Task figure** when the question includes a diagram. Select
  **View task figure** to enlarge it; replacing or removing it updates the task
  independently of the student drawing.
- Select **Begin a revision**, request editing in chat, receive a revision plan,
  or follow direct editing guidance to unlock editing.
- Select **Exit revision** to return to viewing and retain the unsubmitted draft.
  The revision explanation field is disabled outside revision mode.
- Drag a part or connection line. Drag the line's endpoint handles to reshape it,
  or select it and use **+ / −** to resize. Arrow keys also move the selected part.
- Edit text (including text inside objects); move, resize or delete parts and lines.
- Use Undo to restore edits, or reset to the initial reconstruction.
- Add text with **+ Text**; use **+ Object** for a reusable topic library.
- Switch to the original picture; watch automatic highlights and mechanism arrows
  matched to the current feedback. Arrows explain a mechanism; static highlights
  locate or inspect marks.
  Electric-current routing questions prefer automatic directional traces across
  tasks; polarity and any assumed circuit conditions must be supported or qualified.
  Mechanism overlays also work on undirected wires and support Pause and Replay.
- Select Start feedback, respond in chat, and use **I need a hint** for direct guidance.
- Use Review changes to submit a revision. Explain conceptual changes when needed;
  an already-understood operational correction does not need another explanation.
  Submission closes revision mode and disables the revision explanation field.
  If a reason is still needed, the tutor asks for it in chat.
- Expand **Task** to read the task; its collapsed heading remains compact.
- Goal stays visible above chat. Revision suggestions appear in the conversation;
  the pinned Next step/Feedforward panel has been removed.
- Tutor and student have distinct illustrated avatars and consistent bubble colors.
- Draft edits do not silently enter ordinary chat. A **Show** / **Show again** link
  revisits the diagram version used by that feedback. Historical versions are
  read only; Return to my draft restores ongoing work without changing it.
- Save the edited scene and conversation as JSON.
- Select **Export case HTML** above the feedback workspace to download a case
  record for sharing. It includes the task and its figure, original student
  picture, submitted diagram versions, written explanations and the complete
  visible conversation, including any system delivery errors. **Show diagram
  reference** preserves each turn's matching highlights and supported mechanism
  playback. **Move details** reveals the feedback function and move for review.
  The HTML embeds its images, styles and diagrams and opens offline in a browser;
  **Print / Save PDF** expands the references for printing. Export uses submitted
  work and leaves the private draft and conversation unchanged, without an AI call.

No per-object recognition confirmation is required. Ambiguity is retained in
research metadata. Mechanism overlays require resolved, connected paths and explicit conditions
when needed. They are qualitative illustrations rather than numerical circuit
simulations. Manual playback of existing drawn arrows remains available. Prism drawings
are editable 2D outlines, not inferred 3D solids. Chat explains/highlights; it does
not autonomously change the drawing.

The fixed object library lives in `experiments/open_ended_sketch/app/catalog.json`.
It contains 18 editable assets across general diagrams, electricity, energy/water,
states of matter, and mechanics. Add topics/assets there to reuse them in later
tasks; inserting an asset does not call the model. Feedback receives library
provenance so provided marks are not treated as independent student understanding.
Automatic Connection numbers are hidden. Original handwritten line labels remain
editable, and feedback uses visible descriptions plus internal IDs for highlighting.
The ten most recent saved uploads are available in the drawing selector.
The selector also includes fast electric-field and river reconstructions, alongside
the original results. The [latency review](../experiments/open_ended_sketch/results/latency_review_20260923.md)
records single-run reductions from 387 to 100 seconds and 541 to 145 seconds,
including fidelity limitations and exact artifacts. These are not guaranteed times.

Three SketchJudge physics cases are also available: PH_007 (circuit), PH_020
(trolley forces), and PH_036 (two lenses). Their question text loads automatically;
the separate question figure is shown when present and passed to the feedback
evaluator as task context. It is never treated as a student response or answer key.
See the [three-case report](../experiments/open_ended_sketch/results/sketchjudge_physics_review_20260923.md).

The **Math · Integer addition on a number line** example separates the given
question and number-line scaffold from the student's handwritten response in
`data/test-data/math-number-line.jpeg`. Its editable scene was manually traced;
the original labels and uncertain jump directions are retained rather than
corrected. See [the example's provenance](../experiments/open_ended_sketch/results/curated_math_number_line/README.md).

The **Math · Number-line setup** example uses `data/test-data/math-2.jpeg`,
another response to the same question. It preserves the student's labeled axis
without adding jumps or an arithmetic answer. Its given question figure remains
separate from the editable student response. See
[the second example's provenance](../experiments/open_ended_sketch/results/curated_math_2/README.md).

## Reusable prompts and real runs

Recognition (default fast profile): `experiments/open_ended_sketch/prompts/reconstruct_v1.2_compact.md`.
The original `reconstruct_v1.1.md` remains available with the full profile.
Feedback evaluator: `experiments/open_ended_sketch/prompts/feedback_evaluator.md`.
Student-facing tutor: `experiments/open_ended_sketch/prompts/feedback_tutor.md`.
Illustrative patterns: `experiments/open_ended_sketch/prompts/feedback_examples.md`.
Compact text-dialogue policy: `experiments/open_ended_sketch/prompts/feedback_fast_dialogue.md`.
Feedback routing, typed contracts, text–visual validation and orchestration are
separate modules. Task examples remain data; there is no case-specific solution
policy in the feedback prompts or backend.
Shared electric-current guidance supports mechanisms across tasks without
embedding a particular circuit answer. The teacher voice uses explicit supported
praise, warm acknowledgments and occasional scheduled emojis.
Ordinary text replies combine assessment and teaching in one structured call
with a compact committed scene and cached evidence. New diagram submissions and
reviews keep their full evidence path; all routes retain backend validation.
Task figures are read during full assessment. Their instructions and givens are
cached separately from student evidence for later text dialogue; a missing cache
triggers a full assessment instead of dropping the figure's task context.
The server defaults to `FAST_DIALOGUE_MODEL=gpt-6-luna` and
`FAST_DIALOGUE_EFFORT=low` for text-only turns; initial/revised diagram reviews
use `gpt-6-astra`. Change the fast-path environment settings to configure it.
Each feedback run saves `performance.json` with its path and call timings.
A historical local dialogue audit found an approximately 11.7-second median,
including roughly 8–9 seconds of evaluation and 2–3 seconds of writing. The
single-call change targets that overhead; new real-model latency is not yet measured.
The earlier single-stage chat prompt is retained for the legacy `/api/chat` route;
the current student interface uses `/api/feedback`.
Command-line experiments and uploads share profiles in `reconstruction.py`.
The default fast profile uses GPT-6 Astra with low reasoning and a compact wire
schema (`compact.py`): flat coordinate arrays, short field names, concise evidence,
and no generated interaction/simulation prose. A deterministic adapter expands
the output into the unchanged editor/feedback schema. It does not fill missing
geometry or correct the student's model. Quantitative simulation readiness is
explicitly unassessed in this profile. No image downsampling is introduced.

Use `--profile full` with `run.py` to reproduce the previous high-reasoning format.
For uploads, start with `DRAWING_PROFILE=full python3 -B experiments/open_ended_sketch/app/server.py`.
The default is `fast`. There is no automatic second model call or hidden fallback
on a failed reconstruction. Per-image `*.timing.json`, exact prompt/schema snapshots,
the raw compact output and the expanded scene are archived for comparison.

Version 1.1 changes English explanatory output, optional source colors, a general
worksheet/student-panel distinction, and removal of the confirmation requirement.
It adds no task-specific scientific answer or object list. Version 1.0 is retained.

The two energy examples reuse the unedited prior GPT-6 geometry. English titles
and object names are a presentation translation recorded in `app/examples.json`;
they are not new recognition results. Original evidence metadata remains intact.
The prism scene is an independent GPT-6 run with v1.1, saved under
`results/20260923T042443334511Z`. Its input is a crop of the actual student's response;
`inputs/prisms.provenance.json` records source hash and crop bounds. Printed example
solids were excluded. The model returned four objects and no relations.

Upload runs, source images, exact prompts, schemas, responses and scenes are saved
locally in `app/runs/`. Chat requests and responses are saved there too. Uploads
are capped at 10 MB / 20 MP; at most two reconstructions run concurrently. The
service binds to loopback and serves an allowlist of files; it does not expose `.env`.

The October 10 validation includes Python tests, editor and workflow checks,
and browser checks of both screens, editing permissions, revision reasons,
historical references, review, closure and mobile layout using mocked replies.
Real-model validation of the rewritten
prompts requires authorization and is separate from these local checks. Earlier
real GPT-6 results remain historical evidence (`app/live_feedback_check.json`).
Editor tests cover deletion/group cleanup, text, library geometry, and visual targets;
`app/live_visual_guidance_check.json` records a real GPT-6 call on the saved electric
field drawing with an explicitly synthetic explanation.

The supplied ice/water attachment still needs a local file before its independent
API test can run. It is not represented by a substitute or hand-authored model.
