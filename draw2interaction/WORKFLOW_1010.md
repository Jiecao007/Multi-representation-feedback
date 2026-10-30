# Draw to Explore feedback workflow

Table 2 governs feedback content and moves. Table 1 governs how each textual
move is paired with the learner's diagram. The implementation uses a generic
discussion–revision–review cycle, without a task-specific solution script.

## One issue and purposeful progress

The opening explicitly recognizes one supported correct feature and invites
reasoning about that feature. Unverified work receives acknowledgment of its
visible attempt without false praise. The evaluator privately reviews the whole
diagram, then selects one core conceptual or representational issue for dialogue.
Several related marks can share an issue; independent errors receive later cycles.

| Situation | Move and next step |
| --- | --- |
| New supported mismatch | Press for accuracy with neutral observation and one question judging the current diagram against the goal. Keep the diagnosis private and do not ask for a repair yet. |
| Unclear meaning | Revoice or ask for clarification. |
| Developing understanding | Select Build on Prior Knowledge, Invite elaboration/reasoning, Prompt reflection, or Provide hints/guidance when stuck. No fixed order or all-four checklist. |
| Explicit hint or stalled discussion | Give direct guidance or a useful partial solution, rather than another smaller quiz. |
| Sufficient current-issue reasoning | Propose one feasible revision with its purpose. |
| Learner requests revision | Provide a concrete plan and open revision, without another readiness test. |
| Actual changes submitted | Recognize and review the result. Ask about a conceptual change only if its meaning has not already been explained. |
| Correct operational adjustment | Briefly affirm the verified fix, then continue or finish; do not ask another WHY about tool use. |
| Relevant reason accepted | Continue an unresolved issue, select one next independent issue, or invite dialogue if no issues remain. |
| Goal uncertainty | Clarify the expressed uncertainty; otherwise Goal remains above chat. |
| Learner finishes or exits | Acknowledge closure without a compulsory question. |

Feedback support normally precedes a system-initiated revision plan. Its purpose
is enough understanding to choose and try a correction, not a complete theoretical
proof. The tutor takes up established answers instead of repeating WHY tests or
quizzing obvious details. Repeated question targets or stalled turns trigger more
direct guidance; they never count as mastery. Meaningful alternatives can support
understanding but do not become an extra completion gate.

## Revision permissions and explanation

The diagram starts in **view-only** mode. Editing opens only when the learner
selects **Begin a revision**, explicitly requests revision in chat, or the system
enters Feed forward with a revision plan. Feedback guidance also opens editing
when it directly instructs the learner to modify the current diagram. Observation,
comparison, mechanism explanations and other non-editing hints keep it closed.
The writer sets `guidance_requires_edit=true` and `next_step=revise` only for a
direct edit instruction; the backend validates that instruction before authorizing it.
Controls and direct canvas interactions
follow that permission; the backend also rejects unauthorized drawing submissions.

**Exit revision** returns to viewing without submitting, discarding or changing
the private draft, explanation or dialogue. Begin reopens the same draft. Both
buttons use deterministic permission endpoints, without a preset message or AI call.
Exiting preserves any pending conceptual reason; explaining that reason does not
itself reopen editing. The revision explanation field is disabled outside revision
mode; any further explanation of submitted changes belongs in chat.

**Review changes** submits actual geometry and any explanation. The evaluator
distinguishes a conceptual change from an operational adjustment such as aligning
an already-understood arrow. Geometry alone does not establish that distinction:
an arrow move can change a represented concept or relationship. A verified
operational fix with grounded prior learner understanding receives brief specific
praise, without another reason question. A relevant earlier explanation of the
exact conceptual change also counts; a blank reason field does not erase it.
Otherwise, missing or insufficient conceptual reasoning does not discard the diagram:
the system keeps the submitted version, recognizes the change, and asks one
focused reason question. A subsequent chat response can supply that reason.
Submitting closes revision mode and disables the revision explanation field,
including when a reason is still pending. The tutor asks for any missing reason
in chat, without reopening editing or resubmitting the drawing. A new cycle can
open revision again through one of the authorized routes.

Initial optional prose, intended edits and an unexamined confirmation are not
automatically reasons for later changes. Accept concise relevant ordinary-language
reasoning; do not require a formal proof or repeat already established explanations.
Ordinary chat never silently submits draft geometry.

## Evidence before a diagnosis

A new mismatch starts with an accuracy check, rather than the tutor announcing
the error and immediately asking where/how to fix it. A static cue or current
mechanism can expose evidence while the learner judges it. The accuracy response
contains only a neutral `check_observation` and one `check_question`, with
`question_purpose=judge_current_diagram` and `reveals_diagnosis=false`.

Ordinary confirmation or explanation requires `learner_diagnosis_evidence`: an
exact, relevant learner quote after that same issue's check, not a vague yes or
earlier reasoning about a successful feature. The accuracy-check timestamp and
issue anchor scope that evidence. An explicit hint or revision request permits
direct help; ordinary stuck escalation requires the current issue's prior check.
Recognition, clarification and another issue's support counters cannot turn a
new error into immediate guidance. Confirmation belongs in a later support move,
with its diagnosis disclosure recorded for review.

## Text–visual pairing

Most diagram-specific turns automatically show relevant evidence. Choose the
visual according to the current textual purpose:

- **Highlight:** locate, acknowledge, inspect or compare specific diagram marks,
  identify a revision target, or refer to an actual change.
- **Trace:** explain or ask about a mechanism involving movement, routing,
  causation or a process. The words must address that exact mechanism.
- **None:** an abstract explanation, brief encouragement, closure, or another
  turn where a diagram cue adds little.

An available path or previous animation does not justify replaying it every
turn. Static highlights are often enough when the conversation moves from
investigating a mechanism to choosing an action. Direct guidance may give a
bounded useful target; current wrong marks remain inspectable evidence.

All electric-current tasks receive the same domain guidance: when the question
concerns current routing, passing through components, or splitting/rejoining,
use automatic directional traces on supported submitted routes. Placement-only
and revision instructions may remain static. Conventional current direction
requires known polarity and scientific evidence. Unknown polarity is explicitly
qualified in a qualitative route illustration; no screen-position assumption
or invented connection establishes direction. A hypothetical closed switch is
stated as a condition without changing the original open switch or topology.

Mechanism overlays use at most two labeled paths through existing connected
relations, with validated forward/backward steps and explicit conditions when
needed. The evaluator supplies domain meaning and direction. The backend checks
geometry; it does not infer a task-specific scientific solution. Overlays never
invent missing connections, alter the model or provide quantitative simulation.
Pause/Replay and reduced-motion presentation remain available.

**Show / Show again** replays the exact referenced submitted version and cue.
Replay is read-only and preserves the current draft and editing authorization.
It never sends a message, requests revision or opens editing controls. Returning
to the draft restores its existing permissions. New learner turns clear old cues
before applying the new plan.

## Interface

The submission screen collects Task, Student response (diagram and optional
text), and optional Learning requirements. The feedback screen has the diagram
on the left and conversation on the right. The compact heading displays only
**Task**; expand it to read the actual task. Goal stays above chat. Revision
suggestions appear in the conversation; there is no pinned Next step panel.

**I need a hint** sends explicit help intent and receives direct instruction.
**Begin a revision** immediately opens editing, with a deterministic authorization
request and no preset chat message or AI call.
**Exit revision** closes editing while keeping the private work available.
A revision-explanation field supports conceptual changes when needed. Tutor and student have distinct SVG
avatars, consistent pale-lavender bubbles, 18px conversation text and larger
controls. The layout stacks panels on narrower screens.

The tutor uses a lively, kind teacher voice, explicitly praises supported
choices and acknowledges difficulty. A friendly opening emoji and scheduled
occasional later emojis keep the tone expressive without a fixed catchphrase,
false praise or long information-heavy replies.

## Sharing a learning case

**Export case HTML** creates a self-contained, offline case record with task text
and figure, the original student image, submitted diagram snapshots, initial
written explanation, revision reasons and the ordered visible interaction log.
The log also retains unsuccessful requests and labels delivery errors as system
notices. Export does not add a dialogue turn, call a model, change editing
permission or submit the private draft.

Each feedback turn keeps its own **Show diagram reference**, matching highlights
and validated mechanism paths and conditions. **Move details** exposes only the
named feedback function, move and stage. Embedded diagrams, images and styles
require no running app or internet access. **Print / Save PDF** expands the
references and uses static mechanism arrows. The rendering module is
`experiments/open_ended_sketch/app/case_export.js`; the collector and download
button live in `app.js`.

## Prompt and implementation modules

- `experiments/open_ended_sketch/prompts/feedback_evaluator.md`: private evidence,
  progress, move and current visual intent.
- `experiments/open_ended_sketch/prompts/feedback_tutor.md`: concise teaching,
  direct guidance, revision reasons and text–visual pairing.
- `experiments/open_ended_sketch/prompts/feedback_dialogue.md`: message boundaries.
- `experiments/open_ended_sketch/prompts/feedback_fast_dialogue.md`: combined
  assessment/reply for text-only turns, with the same routing and visual rules.
- `experiments/open_ended_sketch/prompts/feedback_examples.md`: short illustrative
  response patterns; these are not task answers or a required dialogue sequence.
- `experiments/open_ended_sketch/app/feedback_types.py`: typed evaluator/tutor contracts.
- `experiments/open_ended_sketch/app/feedback_policy.py`: move routing, progress,
  grounded revision understanding and conditional edit guidance.
- `experiments/open_ended_sketch/app/dialogue_context.py`: compact known diagram
  evidence, routing context and teacher-style scheduling for text-only turns.
- `experiments/open_ended_sketch/app/visual_feedback.py`: generic path validation
  and current text–visual coordination.
- `experiments/open_ended_sketch/app/feedback.py`: evaluation/tutor orchestration,
  reply validation and session boundaries.
- `experiments/open_ended_sketch/app/`: UI, permission-controlled editor,
  historical references, avatars and qualitative mechanism geometry.

Ordinary text dialogue uses one structured model call for assessment and reply,
with the previous assessment, compact committed diagram and recent dialogue.
It does not resend the source image or reconstruct the drawing. Submission and
actual diagram reviews retain the full evidence path. Deterministic routing and
reply validation still apply; a mismatch may require one corrective writer call.
This reduces routine dialogue calls without bypassing editing or reason gates.
The server defaults to `gpt-6-luna` with `low` effort for this combined path;
`FAST_DIALOGUE_MODEL` and `FAST_DIALOGUE_EFFORT` configure it. Initial submissions
and changed-diagram reviews use `gpt-6-astra`. Performance artifacts record the
selected path, individual call duration, input size and available token usage.

An audit of previously saved local dialogue runs found a median total duration
of about 11.7 seconds, with roughly 8–9 seconds in evaluation and 2–3 seconds
in writing. These historical observations explain why combining the two stages
is useful; they do not measure the new path or promise a particular response time.

## Local validation

From the project root:

```sh
python3 -B -m unittest discover -s experiments/open_ended_sketch/tests -p 'test_*.py'
```

JavaScript suites test editor geometry, snapshot boundaries and visual handling.
`test_two_screen_browser.mjs` exercises the local interface with mocked replies,
including revision permissions and reasons, current/historical cues, task expansion
and responsive layouts. It also verifies immediate exit locking, draft preservation,
authorization failure recovery and guidance-specific access. These checks validate implementation behavior; they do
not establish the quality or consistency of real generated feedback. Rewritten
prompts are tested without sending learner data to a model provider.
