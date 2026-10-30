"""Formal assessment, called only for initial or changed diagram submissions."""
from pathlib import Path
from agent_types import EvaluationResult

PROMPT = Path(__file__).resolve().parents[1] / 'prompts/feedback_evaluator.md'


class EvaluationAgent:
    def __init__(self, calls, model):
        self.calls, self.model = calls, model

    def evaluate(self, context, student_image=None, question_image=None):
        images = []
        if student_image:
            label = ('STUDENT ORIGINAL FIGURE: the current initial response.' if context['reason']=='initial' else
                     'STUDENT ORIGINAL FIGURE: reference for the initial work; submitted_work.scene is the current edited response.')
            images.append((label, student_image))
        if question_image:
            images.append(('TASK FIGURE: task givens and scaffold, not a student answer or a reference solution.', question_image))
        return self.calls.call('evaluation', PROMPT.read_text(), context, EvaluationResult,
                               self.model, max_output_tokens=2600, images=images)

