"""Check the wire-format change cannot alter visible marks or editor references."""
import json
from pathlib import Path
import sys
import unittest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
from compact import pack, expand
from schema import validate_sketch
from reconstruction import profile, decode


class CompactTests(unittest.TestCase):
    def test_visual_fields_round_trip(self):
        files=list((HERE/'results/20260922T035929331824Z').glob('*.scene.json'))
        files.append(HERE/'app/runs/upload_ec79d3497ee1452db01c20da95c6c8d4/drawing.scene.json')
        for path in files:
            original=validate_sketch(json.loads(path.read_text())).model_dump()
            wire=pack(original);restored=expand(wire).model_dump()
            self.assertEqual(restored['objects'],original['objects'])
            self.assertEqual(restored['uncertainties'],original['uncertainties'])
            self.assertEqual(restored['omitted_details'],original['omitted_details'])
            for before,after in zip(original['relations'],restored['relations']):
                self.assertEqual({k:v for k,v in before.items() if k!='interpretation'},
                                 {k:v for k,v in after.items() if k!='interpretation'})

    def test_invalid_geometry_and_references_fail_closed(self):
        original=json.loads((HERE/'results/20260922T035929331824Z/pic1.scene.json').read_text())
        wire=pack(original).model_dump();wire['relations'][0]['p'].append(1)
        with self.assertRaises(ValueError):expand(wire)
        wire=pack(original).model_dump();wire['objects'][0]['b']=[999,0,20,30]
        with self.assertRaises(ValueError):expand(wire)
        wire=pack(original).model_dump();wire['relations'][0]['s']='invented-object'
        with self.assertRaises(ValueError):expand(wire)
        wire=pack(original).model_dump();wire['relations'][0]['p'][0]=float('nan')
        with self.assertRaises(ValueError):expand(wire)

    def test_full_profile_remains_available(self):
        original=json.loads((HERE/'results/20260922T035929331824Z/pic1.scene.json').read_text())
        self.assertEqual(profile('full')['effort'],'high')
        self.assertEqual(profile('fast')['effort'],'low')
        self.assertEqual(decode(original,'full'),validate_sketch(original))
        with self.assertRaises(ValueError):profile('unknown')


if __name__=='__main__':unittest.main()
