"""Faithful uploaded-figure conversion, independent of tutoring and evaluation."""
from reconstruction import profile, decode


class TransformationAgent:
    def __init__(self, client, model, profile_name='fast'):
        self.client, self.model, self.profile_name = client, model, profile_name

    def transform(self, drawing_image, task='', question_image=None, image_size=None):
        config = profile(self.profile_name)
        prompt = config['prompt'].read_text()
        dimensions = f' Image dimensions: {image_size[0]} x {image_size[1]} pixels.' if image_size else ''
        content = [{'type':'input_text','text':'STUDENT DRAWING.' + dimensions + '\nTASK CONTEXT: ' + (task or 'Use the separately labeled question image if provided.')},
                   {'type':'input_image','image_url':drawing_image,'detail':'original'}]
        if question_image:
            content.extend([{'type':'input_text','text':'QUESTION IMAGE: given task and scaffold, not a student response or reference answer. Reconstruct only the preceding STUDENT DRAWING; use this image as task context.'},
                            {'type':'input_image','image_url':question_image,'detail':'original'}])
        response = self.client.responses.parse(model=self.model, instructions=prompt,
                    reasoning={'effort':config['effort']}, max_output_tokens=config['max_output_tokens'],
                    store=False, text_format=config['format'], input=[{'role':'user','content':content}])
        if response.status != 'completed' or response.output_parsed is None:
            raise ValueError('The transformation did not finish. Try submitting the drawing again.')
        return response, decode(response.output_parsed, self.profile_name).model_dump()
