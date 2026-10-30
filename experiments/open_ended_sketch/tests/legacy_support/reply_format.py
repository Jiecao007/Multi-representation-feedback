"""Repair redundant output fields without changing the tutor's teaching text."""
from copy import deepcopy


def canonical_reply(reply,assessment):
    reply=reply.model_copy(deep=True)
    # The validated assessment owns the overview; the writer need not recreate it.
    reply.review=deepcopy(assessment.criteria)
    observation=reply.check_observation.strip();question=reply.check_question.strip()
    if question and observation.endswith(question) and reply.content.strip()==observation:
        # Some outputs copy the full paragraph into observation. Remove only the
        # identical trailing question, leaving all diagnostic prose for validation.
        reply.check_observation=observation[:-len(question)].strip()
    if reply.visual_action=='trace':
        requested=list(dict.fromkeys(([reply.focus_id] if reply.focus_id else [])+reply.focus_ids))
        if len(requested)>4:
            steps={s.relation_id for p in reply.mechanism_paths for s in p.steps}
            # Animated steps have their own channel and remain intact there.
            reply.focus_ids=[i for i in requested if i==reply.focus_id or i not in steps]
            if not reply.focus_ids:reply.focus_ids=requested[:1]
    return reply
