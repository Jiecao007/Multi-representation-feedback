"""Reject references that could misrepresent or break editable relationships."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from schema import validate_sketch


def fixture():
    return dict(title='test',summary='',representation='test',objects=[
        dict(id='a',label='a',verbatim_text='',kind='object',bbox=dict(x=0,y=0,width=10,height=10),
             glyph=[],members=[],origin='student',confidence=1,evidence='',ambiguity=''),
        dict(id='b',label='b',verbatim_text='',kind='object',bbox=dict(x=20,y=20,width=10,height=10),
             glyph=[],members=[],origin='student',confidence=1,evidence='',ambiguity='')],
        relations=[dict(id='r',source='a',target=None,direction='forward',points=[dict(x=0,y=0),dict(x=20,y=20)],verbatim_text='',label_position=dict(x=0,y=0),interpretation='',origin='student',confidence=1,evidence='',ambiguity='unresolved endpoint')],
        uncertainties=[],omitted_details=[],simulation_readiness='qualitative_only',simulation_requirements=[],suggested_interactions=[])


class ValidationTest(unittest.TestCase):
    def test_unresolved_is_retained_but_unknown_id_rejected(self):
        s=fixture();self.assertIsNone(validate_sketch(s).relations[0].target)
        s['relations'][0]['target']='invented'
        with self.assertRaises(ValueError):validate_sketch(s)

    def test_group_cycle_rejected(self):
        s=fixture();s['objects'][0]['members']=['b'];s['objects'][1]['members']=['a']
        with self.assertRaises(ValueError):validate_sketch(s)

    def test_invalid_coordinates_rejected(self):
        s=fixture();s['objects'][0]['bbox']['x']=999
        with self.assertRaises(ValueError):validate_sketch(s)
        s=fixture();s['relations'][0]['points'][0]['x']=float('nan')
        with self.assertRaises(ValueError):validate_sketch(s)


if __name__=='__main__':unittest.main()
