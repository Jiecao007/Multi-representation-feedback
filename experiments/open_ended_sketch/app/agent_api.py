"""One typed API call per requested agent; no hidden retries or rewrite calls."""
import json
from pathlib import Path
import time
from pydantic import ValidationError


class AgentError(ValueError):
    pass


class AgentCalls:
    def __init__(self, client, directory):
        self.client = client
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.records = []

    def save(self, name, value):
        (self.directory / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

    def call(self, role, prompt, context, contract, model, effort='low', max_output_tokens=2000, images=()):
        packed = json.dumps(context, ensure_ascii=False, separators=(',', ':'))
        content = [{'type':'input_text', 'text':packed}]
        for label, url in images:
            if url:
                content.extend([{'type':'input_text','text':label},
                                {'type':'input_image','image_url':url,'detail':'original'}])
        (self.directory / (role + '.prompt.md')).write_text(prompt, encoding='utf-8')
        self.save(role + '.input.json', context)
        self.save(role + '.schema.json', contract.model_json_schema())
        record = dict(stage=role, model=model, input_chars=len(packed), effort=effort)
        self.records.append(record)
        started = time.perf_counter()
        try:
            response = self.client.responses.parse(
                model=model, instructions=prompt, input=[{'role':'user','content':content}],
                reasoning={'effort':effort}, max_output_tokens=max_output_tokens,
                store=False, text_format=contract)
            self.save(role + '.response.json', response.model_dump(mode='json', warnings=False))
            usage = getattr(response, 'usage', None)
            if usage:
                record.update({key:getattr(usage,key,None) for key in ('input_tokens','output_tokens')})
            if response.status != 'completed' or response.output_parsed is None:
                raise AgentError('The ' + role + ' response did not finish. Please retry.')
            result = response.output_parsed
            return result if isinstance(result, contract) else contract.model_validate(result.model_dump() if hasattr(result,'model_dump') else result)
        except ValidationError as exc:
            self.save('validation.json', dict(
                problem='The structured response does not match the current ' + role + ' contract.',
                errors=[{key: item[key] for key in ('loc', 'type', 'msg')}
                        for item in exc.errors(include_input=False, include_url=False)],
                automatic_rewrite=False))
            raise AgentError('The ' + role + ' response did not match the current feedback step. '
                             'Your previous feedback is unchanged; please retry.') from exc
        finally:
            record['elapsed_seconds'] = round(time.perf_counter() - started, 3)

