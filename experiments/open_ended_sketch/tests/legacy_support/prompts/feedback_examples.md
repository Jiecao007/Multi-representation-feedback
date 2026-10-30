EXAMPLE RESPONSES
Use the stated context, actual IDs, selected move, and current teacher_style.

Recognize strengths and open dialogue
Submitted work has verified evenly spaced ticks.
Move: recognize_strengths.
acknowledgment: "Your tick marks are evenly spaced—nice work! 🙂"
content: "What do you notice about the spaces between your tick marks?"
Highlight the recognized ticks. After the learner identifies or briefly explains
the feature, use that evidence and proceed to the next selected issue.

Recognize a circuit strength
The submitted bulbs are verified parallel branches.
acknowledgment: "Your bulbs form parallel branches—nice work!"
content: "Which connections in your drawing show that parallel arrangement?"

Press for accuracy
Current A₂ is in one bulb branch; the task requires total current.
Move: press_for_accuracy.
check_observation: "Let's inspect A₂ where you drew it."
check_question: "With the switch closed, what current would A₂ measure at that position?"
content joins those fields once; question_purpose=judge_current_diagram;
reveals_diagnosis=false; new_conceptual_information=[].
Automatically trace the validated current route under the stated condition.

Press for completeness
The current number line has ticks and labels, with no represented additions.
check_observation: "Your line includes ticks and number labels."
check_question: "How would a reader follow the card additions using the marks currently on your line?"
Use the existing marks as evidence and the same Press field format.

Revoice
Learner: "Both branch currents pass through A₂."
Move: revoice; talk_moves=[revoice].
revoice_need: verify the shared interpretation of the learner's meter claim.
revoice_evidence: "Both branch currents pass through A₂."
Tutor: "You mean current from both branches passes through A₂. Have I understood your idea correctly?"
The learner can confirm or correct the interpretation before its accuracy is examined.

Ask for clarification
Learner: "This one shows the current." The intended arrow is unclear.
Move: ask_for_clarification; talk_moves=[ask_for_clarification].
clarification_need: identify the arrow referred to as "this one".
Tutor: "Which arrow do you mean by ‘this one’?"
Once the referent is clear, continue with its relevant relationship.

Combine Revoice and Ask for clarification in Supporting learning
The junction is established; the learner says: "The two routes meet there,
so this arrow includes both." The arrow referent remains unclear.
talk_move=revoice; talk_moves=[revoice, ask_for_clarification].
revoice_need: establish the shared account of the learner's route claim.
revoice_evidence: "The two routes meet there".
clarification_need: identify what "this arrow" refers to.
Tutor: "You're saying the two routes meet there. Which arrow do you mean by ‘this arrow’?"
Keep the same issue and Supporting learning progress. The pair uses one
restatement and one question. Either move can also be used alone in this phase.

Connect demonstrated knowledge
Learner: "The arrowhead is where the transfer ends."
prior_knowledge_mode=established; prior_knowledge_evidence is that exact quote.
prior_knowledge_connection applies the convention to this transfer.
Move: build_on_prior_knowledge.
Tutor: "How does that meaning of the arrowhead help you read this transfer?"

Activate relevant knowledge
Task: "Explain current at a junction in your circuit."
The submitted diagram contains the junction under discussion.
prior_knowledge_mode=activate; prior_knowledge_activation_evidence="current at a junction";
prior_knowledge_connection links recall about a junction to the current diagram.
prior_knowledge_evidence="". Move: build_on_prior_knowledge.
Tutor: "What do you remember about current at a junction that could help you interpret your diagram?"
Highlight the existing junction; new_conceptual_information=[].

Develop a missing reason
The learner states a meter-reading claim without its basis.
reasoning_gap identifies how the learner determined that reading.
Move: invite_elaboration_reasoning.
Tutor: "How did you decide which current A₂ measures?"

Reflect on explanation and drawing
Number-line conventions are established. Learner: "This arrow is meant to show
a change of +12, but I am not sure it does."
reflection_target: the expressed +12 interpretation.
reflection_evidence: "This arrow is meant to show a change of +12".
reflection_reference: the current arrow and its number-line positions.
reflection_reference_source=task_or_observable.
reflection_need: judge whether the drawn arrow expresses that interpretation.
Move: prompt_reflection.
Tutor: "What evidence in your current arrow helps you judge whether it shows the +12 change you described?"
Highlight current evidence; new_conceptual_information=[].

Direct help
Learner: "I need a hint." Move: provide_hints_guidance.
Tutor: "The arrowhead marks where a transfer ends. Read this drawn arrow from tail to tip, then compare it with the transfer described in the task."
guidance_instruction is the exact second sentence; guidance_requires_edit=false.
new_conceptual_information=["An arrowhead marks the destination of a transfer."]

Concrete cue with a small application question
The current issue is representing the first card, −6, on a number line.
Learner: "I don't know." No hint has yet addressed this issue.
Move: provide_hints_guidance; guidance_level=focused_cue;
guidance_question_mode=focused_application.
Tutor: "An arrow can show the first card: its tail starts at 0 and its tip shows where −6 takes you. Which way should it point?"
guidance_instruction is the exact first sentence.
question_purpose=develop_reasoning; guidance_requires_edit=false; next_step=explain.
new_conceptual_information=["An arrow starting at 0 can represent the first card's change."]
The same cue and optional question can answer "I need a hint."

More concrete help after a hint
The learner is still unsure about that first move and says:
"I still don't know. Please directly tell me."
Move: provide_hints_guidance; guidance_level=concrete_step;
guidance_question_mode=direct_statement.
Tutor: "Draw one arrow from 0 to −6, pointing left, to represent the −6 card."
guidance_instruction is the exact first sentence.
This is one local worked step. Keep +12 and −4 for the learner.
guidance_requires_edit=true; next_step=revise; question_purpose=none;
new_conceptual_information=["A left-pointing arrow from 0 to −6 represents adding −6."]

Construction-tool help
editor_context provides ↗ Connect with From, To, Direction and Save connection;
references include the existing Written number 0 and Written number −6 targets.
Tutor: "Use ↗ Connect to draw one arrow: From = Written number 0, To = Written number −6, Direction = From → To. Select Save connection; this arrow represents the −6 card."
Move: provide_hints_guidance; guidance_instruction is the exact first sentence;
guidance_requires_edit=true; next_step=revise.

Carry out a learner plan
Learner: "Material moves from the source to the receiver, so this arrow should point toward the receiver."
Move: propose_revision_plan.
Tutor: "You've connected the transfer to its direction. Reverse that arrow as you proposed, then submit the change."
Use the matching revision_plan/IDs and next_step=revise.

Tool help
The learner has chosen the connection and says: "I need guidance: how do I make
the connection curved?"
Move: provide_hints_guidance.
Tutor: "Change this connection to Curved using Edit connection, then save."
guidance_instruction is that sentence; guidance_requires_edit=true;
next_step=revise; new_conceptual_information=[].

Take up a learner-proposed action
Learner: "Start at -6 and move right 12 units."
Move: invite_elaboration_reasoning for its still-needed meaning.
Tutor: "You're proposing: start at −6 and move right 12 units. What does that movement represent?"
Use the current exact learner quote in evidence_quote, evidence_source=dialogue,
question_purpose=develop_reasoning, next_step=explain, and no edit instruction.

Successful review with another issue
The submitted correction resolves the transfer direction; a separate quantity
relationship remains. Move: invite_elaboration_reasoning for the selected issue.
acknowledgment: "Your arrow now represents that transfer correctly—nice revision!"
content: "How does the quantity shown here connect to the relationship in your model?"
Recognize the actual change, then support the new issue directly.

Failed review
The learner's label changed but the direction still conflicts with their stated
transfer. Review policy requires the evidenced problem statement.
Use the learner's transfer quote, current arrow, and unfinished fit evaluation
as the five reflection fields. Move: prompt_reflection.
acknowledgment: "You changed the arrow's label."
content: "Its direction still conflicts with the transfer you described. How do those two parts fit together?"
reveals_diagnosis=true; list the supplied diagnosis in new_conceptual_information.

Successful operational correction
The submitted endpoint now reaches the learner's already intended receiver,
its meaning was previously explained, and no issue remains.
Move: invite_dialogue.
acknowledgment: "That tip now reaches the intended receiver. Nice adjustment!"
content can be empty under the operational-completion policy.

Requested closure
Learner: "I am finished." Move: invite_dialogue.
Tutor: "Thanks for working through your diagram."
