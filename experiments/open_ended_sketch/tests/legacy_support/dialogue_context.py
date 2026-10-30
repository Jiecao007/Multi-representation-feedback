"""Compact known drawing evidence for fast, text-only tutoring turns."""
from copy import deepcopy
import re

EMOJI=re.compile(r'[\U0001F300-\U0001FAFF\u2600-\u27BF]')


def teacher_style(state,trigger):
    recent=[t['content'] for t in state['turns'][-2:]]
    expected=trigger=='submission' or (len(recent)==2 and not any(EMOJI.search(s) for s in recent))
    return {'tone':'warm, encouraging, attentive','emoji_expected':expected}


def diagram_evidence(scene):
    """Keep all referents and topology, omitting repeated rendering strokes."""
    objects=[{k:deepcopy(o[k]) for k in ('id','label','verbatim_text','kind','bbox','members','origin','ambiguity')}
             for o in scene['objects']]
    relations=[{k:deepcopy(r[k]) for k in ('id','source','target','direction','points','verbatim_text','origin','ambiguity')}
               for r in scene['relations']]
    return {'title':scene['title'],'objects':objects,'relations':relations}


def compact_context(context,state):
    omitted={'original','committed','previous_submission','source_id'}
    result={k:deepcopy(v) for k,v in context.items() if k not in omitted}
    result['committed']={'scene':diagram_evidence(state['committed']['scene']),
                         'explanation':state['committed']['explanation']}
    result['original_explanation']=state['original']['explanation']
    if state.get('awaiting_revision_reason') and state.get('previous_submission'):
        result['previous_submission']={'scene':diagram_evidence(state['previous_submission']['scene']),
                                      'explanation':state['previous_submission']['explanation']}
    result['routing_state']={k:deepcopy(state[k]) for k in ('version','accuracy_focus','accuracy_started_at','thinking_focus','thinking_started_at',
                             'progress_focus','issue_turn_count','thinking_opportunity_count','last_question_target','edit_enabled','awaiting_revision_reason',
                             'response_progress_focus','unsuccessful_response_count','response_progress_version','last_response_frustration',
                             'issue_check_focus','issue_check_started_at','review_support_focus','review_outcome')}
    return result
