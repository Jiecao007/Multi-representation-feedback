"""Shared reconstruction profiles for uploads and independent API experiments."""
from pathlib import Path
from compact import CompactSketch, expand
from schema import Sketch, validate_sketch

HERE=Path(__file__).resolve().parent
PROFILES={
    'fast':dict(format=CompactSketch,prompt=HERE/'prompts/reconstruct_v1.2_compact.md',effort='low',max_output_tokens=16000),
    'full':dict(format=Sketch,prompt=HERE/'prompts/reconstruct_v1.1.md',effort='high',max_output_tokens=24000),
}

def profile(name):
    if name not in PROFILES:raise ValueError('Drawing profile must be fast or full')
    return PROFILES[name]

def decode(value,name):
    return expand(value) if name=='fast' else validate_sketch(value)
