"""Given task figures are validated and transported separately from student work."""
import base64
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from test_student_server import server, FakeResponse


def image_data(format_='PNG',color='white'):
    data=io.BytesIO();Image.new('RGB',(16,12),color).save(data,format=format_)
    mime='image/jpeg' if format_=='JPEG' else 'image/'+format_.lower()
    return 'data:'+mime+';base64,'+base64.b64encode(data.getvalue()).decode()


def dispatch(path,data):
    """Exercise HTTP parsing without opening a network socket."""
    raw=json.dumps(data).encode()
    response=Mock()
    handler=SimpleNamespace(path=path,headers={'Content-Type':'application/json','Content-Length':str(len(raw))},
                            rfile=io.BytesIO(raw),allowed=lambda:True,json=response)
    server.Handler.do_POST(handler)
    return response.call_args.args


class GivenFigureTests(unittest.TestCase):
    def test_optional_missing_none_and_clear_are_accepted(self):
        for data in ({},{'question_image':None},{'question_image':''},{'image':image_data()}):
            with self.subTest(keys=list(data)):
                self.assertIsNone(server.decode_question_image(data))

    def test_given_figures_accept_same_three_formats_as_student_images(self):
        for format_ in ('PNG','JPEG','WEBP'):
            with self.subTest(format=format_):
                data=image_data(format_)
                self.assertEqual(server.decode_question_image({'question_image':data}),data)

    def test_invalid_type_remote_url_and_unsupported_format_are_rejected(self):
        for data in (False,42,[],{},'https://example.org/question.png','data:image/svg+xml;base64,PHN2Zz4=',
                     'data:image/gif;base64,R0lGODlh','data:image/png;base64,not-base64!',
                     'data:image/png;base64,'+base64.b64encode(b'not an image').decode()):
            with self.subTest(value_type=type(data).__name__):
                with self.assertRaisesRegex(ValueError,'Task figure:'):
                    server.decode_question_image({'question_image':data})

    def test_oversized_given_image_is_rejected_before_decoding_pixels(self):
        with patch.object(server.base64,'b64decode',return_value=b'x'*(10*1024*1024+1)),patch.object(server.Image,'open') as opened:
            with self.assertRaisesRegex(ValueError,'10 MB'):
                server.decode_question_image({'question_image':image_data()})
            opened.assert_not_called()

    def test_given_image_above_twenty_megapixels_is_rejected(self):
        class OversizedImage:
            size=(5001,4000);format='PNG'
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def verify(self):raise AssertionError('Oversized image should be rejected first.')
        given=image_data()
        with patch.object(server.Image,'open',return_value=OversizedImage()):
            with self.assertRaisesRegex(ValueError,'20 megapixels'):
                server.decode_question_image({'question_image':given})

    def test_body_limit_can_carry_two_valid_ten_megabyte_images(self):
        encoded_image_size=4*((10*1024*1024+2)//3)
        self.assertGreater(server.MAX_BODY,2*encoded_image_size+4000)

    def test_bad_task_figure_stops_reconstruction_before_queuing_or_client_use(self):
        with patch.object(server.POOL,'submit') as queued,patch.object(server,'client') as client:
            status,_=dispatch('/api/reconstruct',{'image':image_data(),'question_image':'https://example.org/task.png'})
            self.assertEqual(status,400)
            queued.assert_not_called();client.assert_not_called()

    def test_empty_text_task_and_given_image_are_forwarded_as_separate_uploads(self):
        student=image_data();given=image_data('JPEG','lightblue')
        with patch.object(server.POOL,'submit') as queued,patch.dict(server.JOBS,{},clear=True),\
                patch.dict(server.os.environ,{'OPENAI_API_KEY':'test-only'}):
            status,_=dispatch('/api/reconstruct',{'image':student,'task':'','question_image':given})
            self.assertEqual(status,202)
            args=queued.call_args.args
            self.assertIs(args[0],server.reconstruct)
            self.assertEqual(args[2],base64.b64decode(student.split(',',1)[1]))
            self.assertEqual(args[-2:],('',given))

    def test_feedback_validates_explicit_figure_before_creating_client(self):
        with patch.object(server,'client') as client,patch.object(server.feedback,'handle') as handle:
            status,_=dispatch('/api/feedback',{'trigger':'submission','question_image':False})
            self.assertEqual(status,400)
            client.assert_not_called();handle.assert_not_called()

    def test_feedback_explicit_figure_override_clear_and_absent_example_fallback(self):
        given=image_data('JPEG','lightblue');cached=image_data('PNG','pink')
        for provided,expected in (({'question_image':given},given),({'question_image':''},None),
                                  ({'question_image':None},None),({},cached)):
            with self.subTest(explicit='question_image' in provided,value_present=bool(provided.get('question_image'))),\
                    patch.object(server,'examples',return_value=[{'id':'example'}]),\
                    patch.object(server,'read_payload',return_value={'question':{'image':cached}}) as read,\
                    patch.object(server,'client',return_value=object()),\
                    patch.object(server.feedback,'handle',return_value={'content':'Test response.'}) as handle:
                status,_=dispatch('/api/feedback',dict(trigger='submission',source_id='example',**provided))
                self.assertEqual(status,200)
                self.assertEqual(handle.call_args.kwargs['question_image'],expected)
                self.assertEqual(read.call_count,1)  # Original student image is resolved independently of the task-figure override.

    def test_ordinary_feedback_message_cannot_replace_the_original_given_figure(self):
        with patch.object(server,'client',return_value=object()),\
                patch.object(server,'examples') as examples,\
                patch.object(server.feedback,'handle',return_value={'content':'Test response.'}) as handle:
            status,_=dispatch('/api/feedback',{'trigger':'message','session_id':'cached','message':'My idea.',
                                             'question_image':'untrusted replacement'})
            self.assertEqual(status,200)
            self.assertIsNone(handle.call_args.kwargs['question_image'])
            examples.assert_not_called()

    def test_reconstruction_with_empty_task_keeps_question_and_student_roles_separate(self):
        student=image_data('PNG','white');given=image_data('JPEG','lightblue')
        raw,size,suffix=server.decode_upload({'image':student})
        calls=[]
        def parse(**kwargs):calls.append(kwargs);return FakeResponse()
        fake=SimpleNamespace(responses=SimpleNamespace(parse=parse))
        job_id='upload_task_figure_stub'
        with tempfile.TemporaryDirectory() as tmp,patch.object(server,'ARTIFACTS',Path(tmp)),patch.object(server,'client',return_value=fake):
            server.reconstruct(job_id,raw,size,suffix,'',given)
            result=server.JOBS[job_id]
            self.assertEqual(result['status'],'completed')
            self.assertEqual(len(calls),1)
            parts=calls[0]['input'][0]['content']
            self.assertEqual([part['type'] for part in parts],['input_text','input_image','input_text','input_image'])
            self.assertIn('STUDENT DRAWING',parts[0]['text'])
            self.assertIn('QUESTION IMAGE',parts[2]['text'])
            self.assertIn('not a student response',parts[2]['text'])
            self.assertEqual(parts[1]['image_url'],student)
            self.assertEqual(parts[3]['image_url'],given)
            payload=result['payload']
            self.assertEqual(payload['original'],student)
            self.assertEqual(payload['question']['image'],given)
            self.assertEqual(payload['question']['text'],'')
            self.assertEqual(payload['record']['sha256'],hashlib.sha256(raw).hexdigest())
            source=Path(payload['record']['original_path'])
            question=Path(payload['record']['question_image_path'])
            self.assertEqual(source.read_bytes(),raw)
            self.assertNotEqual(source,question)
            self.assertEqual(question.read_bytes(),base64.b64decode(given.split(',',1)[1]))
            restored=server.read_payload({'upload':job_id})
            self.assertEqual(restored['question'],payload['question'])
            self.assertEqual(restored['scene'],payload['scene'])

    def test_student_only_reconstruction_keeps_single_image_contract(self):
        student=image_data();raw,size,suffix=server.decode_upload({'image':student});calls=[]
        def parse(**kwargs):calls.append(kwargs);return FakeResponse()
        fake=SimpleNamespace(responses=SimpleNamespace(parse=parse))
        with tempfile.TemporaryDirectory() as tmp,patch.object(server,'ARTIFACTS',Path(tmp)),patch.object(server,'client',return_value=fake):
            server.reconstruct('upload_no_task_figure_stub',raw,size,suffix,'A text task')
            result=server.JOBS['upload_no_task_figure_stub']
            self.assertEqual(result['status'],'completed')
            self.assertIsNone(result['payload']['question'])
            self.assertEqual(len([p for p in calls[0]['input'][0]['content'] if p['type']=='input_image']),1)


if __name__=='__main__':unittest.main()
