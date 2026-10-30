# Mechanics Studio → Draw to Explore

The earlier system was found at:

`/Users/jiecao/Library/CloudStorage/OneDrive-UniversityofNorthCarolinaatChapelHill/26 Spring/Indepentent study/Ha/BJET_feedback_26/outputs/mechanics-feedback-demo`

Its README describes **Mechanics Studio — interactive original drawing**, a Tow
Truck feedback prototype with a conversation, Overall feedback, submitted drawing
annotations, and an optional incline experiment. This matches the requested prior
work more closely than the separate calculus and desktop feedback projects.

## What was integrated

| Original implementation | Current implementation | Preserved behavior |
| --- | --- | --- |
| `lib/talk-moves.ts` | `app/feedback.py` and `prompts/feedback_*.md` | Internal evaluator → student-facing tutor; talk-move selection; first-turn Feedback; readiness-gated Feed-forward; 60-word turns with response recognition followed by a focused inquiry; one rewrite |
| `lib/review-boundary.ts` | `app/workflow.js`, server `prepare()` | Draft edits stay outside chat until explicit submission; written revision does not silently submit a drawing |
| `lib/feedback-workflow.ts` | `app/feedback.py`, Overall feedback UI | Complete criterion review; retain unchanged rows; original work separate from revisions; validate exact quotes; preserve previous review on failure |
| `app/api/chat/route.ts` | `/api/feedback` in `app/server.py` | Two separate real model calls; private assessment never returned to student; validated short feedback |

All current relative paths above are under `experiments/open_ended_sketch/`.
The four original source files are snapshotted in `legacy_reference/` with hashes
and full paths. Their TypeScript logic was adapted to the existing Python/vanilla
JavaScript workspace. The old Next/Vinext app, secrets, hosting configuration,
prepared physics geometry, and task-specific answer reference were not copied.
The original project was only read, not modified.

## Deliberate task-general adaptations

- Initial/revised submissions use **gpt-6-astra** for evaluator and tutor. Ordinary chat uses one **gpt-6-sol** low-reasoning call with cached assessment and the committed drawing. No scripted feedback or silent model fallback.
- Replace fixed `machines / forces / newton` criteria with up to five configurable
  feedback goals. Without configured goals, use three clearly labeled exploratory
  lenses: visible representation, relationships/spatial structure, explanation/evidence.
  These defaults are not represented as the original teacher's rubric or a grade.
- Replace the fixed tow-truck image surface with the new independently recognized
  objects. Preserve the user's requested drag, resize, rename and arrow exploration.
- Add editable text, connections and a reusable topic object library so feedback
  can lead to drawing revisions. Parts and lines can be deleted and edits undone.
  Stable IDs stay internal; visible references use original labels or descriptions.
- Tutor output includes up to four validated object/relation IDs. The canvas
  highlights these parts, dims the surroundings, and provides a **Show on model**
  focus action beside the message. Deleted targets are reported instead of silently
  highlighting another part. Preset library marks retain their provenance.
- Keep AI-assigned object names separate from student-authored labels and explicit
  edits. The evaluator receives edit records only when submitted. Movement and
  animation alone do not demonstrate conceptual progress.
- Keep the original photo available. The system currently reasons from the
  structured reconstruction and submitted writing; evaluator/tutor stages do not
  independently inspect the original pixels again. Recognition error remains a
  limitation. The drawing schema retains uncertainty without student confirmation.
- Do not import the old incline solver into unrelated diagrams. Arrow playback is
  a representation-level animation, not a physical prediction.

## Student flow

1. Choose an existing example, or **Submit picture** (GPT-6 recognition).
2. Add an explanation if requested by the task or if you want to share reasoning; optionally specify task context and feedback goals.
3. **Get feedback** starts the evaluator/tutor sequence. A newly uploaded picture
   starts this sequence automatically using the current explanation and task fields.
4. Read the recognition of your submitted response in Chat, highlighted in teal. A focused question appears directly below the recognition; hover or focus it to see the corresponding drawing marks. The **Overall feedback** panel starts collapsed.
5. Explain in Chat, or edit, add, move, resize or delete parts on the canvas.
6. **Review changes** explicitly submits the drawing plus current explanation.
   Ordinary chat continues to use the last submitted drawing/explanation.
7. **Save** exports original model, committed work, draft work, edit events,
   conversations, review snapshots and model provenance.

The server maintains the committed feedback session in memory and archives each
successful session snapshot and raw model responses locally in `app/runs/`.
A server restart ends active in-memory sessions; Get feedback starts a fresh one.
No student accounts or deployed shared service were introduced.

## Validation

- `test_feedback.py`: submission boundaries, immutable initial work, dynamic goals,
  talk-move/readiness gates, short-turn rules, private output separation, one rewrite,
  exact quote validation, unchanged rows, atomic state on failed/invalid responses.
- `test_feedback_workflow.cjs`: browser-side committed/draft snapshots.
- `test_editor.cjs`: text and mixed objects, all 18 library assets, deletion/group
  cleanup, snapshots, semantic line names and multiple visual targets.
- `live_visual_guidance_check.py`: real GPT-6 feedback with valid visual targets on
  the saved electric-field upload; explanation explicitly marked synthetic.
- Existing geometry, schema and HTTP tests retained.
- `live_feedback_check.py`: three real GPT-6 feedback turns using **synthetic**
  student explanations on the existing energy example; each turn invokes evaluator
  and tutor independently. Results are recorded in `app/live_feedback_check.json`.
- Browser visual/interaction testing was not performed in this iteration.

## Response-first feedback (2026-09-23)

Initial and resubmitted work receives a concrete acknowledgment with its own
`acknowledgment_ids`. An actual gap, genuine ambiguity, or requested extension has
a separate `follow_up` and `focus_ids`, displayed immediately after recognition.
A satisfied task invites an `extension` without an invented deficit; `none` is
reserved for explicit learner closure.
Unrequested written reasoning receives `not-requested`, with no invented gap.
Selected editor objects are cleared when feedback applies a cue, so a template
selection does not masquerade as tutor focus. Teal denotes recognition, not a grade.

Validated with 17 Python tests, editor/geometry/workflow Node checks, and
`test_response_first.cjs` (UI sequence and cue switching). Real GPT-6 regression
`live_response_first_check.py` recognized both correct arrows in PH_020 (16.429 s)
and separately raised a friction-direction issue in a synthetic reversed-arrow
variant (19.529 s). Outputs: `results/response_first_feedback_20260923T150658Z.json`.
Those historical checks captured the earlier completion policy; the dialogue-continuation revision below supersedes its no-question behavior. They do not establish general
accuracy across all student drawings. No browser visual testing in this change.

## Dialogue continuation revision

The system now actively invites one grounded student response after recognition:
a real gap first, genuine ambiguity next, or deeper reasoning/prediction when the
drawing meets the task. Missing optional writing remains ungraded. The evaluator
chooses the inquiry; the tutor does not hard-code topic questions. If a non-closing
assessment returns `none`, the server requests an extension from the tutor without
changing review statuses. Explicit learner closure can end without another question.

Recognition and inquiry share one message; no button hides the question. Initial
teal focus shows the recognized work, while hovering/focusing the question (or its
Show on model button) applies its separate visual targets. The model workspace is
on the left, Feedback on the right, with a full-width responsive layout.

`live_dialogue_continuation_check.py` tests PH_036's real drawing and a clearly
marked synthetic learner reply expressing uncertainty. Initial feedback contains a grounded inquiry; later conversation may answer directly or ask at most one question. Raw responses are
archived by the server; dated public results go in `results/dialogue_continuation_*.json`.

## Natural, faster conversation

`prompts/feedback_dialogue.md` is the ordinary-chat prompt, separate from the
initial/revised-work evaluator and tutor prompts. Its compact output only contains
conversation text and visual targets. It neither produces a praise/acknowledgment
section nor requires a question on every turn. Conceptual questions get direct
help; student replies, uncertainty and closure receive context-specific responses.

`message` uses a single Responses call to GPT-6 Sol (low reasoning, 1,800 token cap),
with one rewrite only if structural validation fails. The cached private assessment,
last committed geometry/uncertainties and up to 16 prior turns supply context. It
does not resend images or the full duplicate original drawing. Unsubmitted edits
remain private; `workspace-complete`/`revision` returns to the two-stage Astra route.
The Overall feedback rows/review number are frozen during chat and refreshed on
explicit review, which includes the conversation. Normal chat does not refit the
canvas or collapse the review panel.

Configuration (optional in local `.env`, restart required):
```dotenv
DIALOGUE_MODEL=gpt-6-sol
DIALOGUE_EFFORT=low
```
The default is low reasoning; `none` is also supported by Sol. Model support verified
against [official OpenAI Docs](https://developers.openai.com/api/docs/models/gpt-6-sol).
Each public archived turn records response mode, model, API call count and elapsed
seconds. `live_fast_dialogue_check.py` tests the real trolley drawing followed by
synthetic learner dialogue; tests verify single-call routing, no repeated
acknowledgment block, stable drawing review, and explicit closure.

Live check on 2026-09-23: initial Astra review took 14.242 s (two calls);
three Sol dialogue replies took 2.975, 3.257 and 2.150 s (one call each). The
learner messages were synthetic; the drawing was the saved PH_020 response.
Results: `results/fast_dialogue_20260923T180337Z.json`. All 18 Python regressions
and the response-first UI/workflow Node checks passed. No browser visual test
was performed; measured times are a small local sample, not a latency guarantee.
