"""Domain-independent, declarative visual objects. Never executable model code."""
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Point(Strict):
    x: float = Field(ge=0, le=1000)
    y: float = Field(ge=0, le=1000)


class Box(Strict):
    x: float = Field(ge=0, le=1000)
    y: float = Field(ge=0, le=1000)
    width: float = Field(gt=0, le=1000)
    height: float = Field(gt=0, le=1000)


class Stroke(Strict):
    kind: Literal['polyline', 'polygon', 'ellipse', 'rect', 'text']
    points: list[Point]
    text: str
    filled: bool
    color: Optional[str] = Field(default=None, pattern=r'^#[0-9a-fA-F]{6}$')


class Object(Strict):
    id: str
    label: str
    verbatim_text: str
    kind: str
    bbox: Box
    glyph: list[Stroke]
    members: list[str]
    origin: Literal['student', 'template', 'uncertain']
    confidence: float = Field(ge=0, le=1)
    evidence: str
    ambiguity: str


class Relation(Strict):
    id: str
    source: Optional[str]
    target: Optional[str]
    direction: Literal['forward', 'backward', 'both', 'none', 'uncertain']
    points: list[Point]
    verbatim_text: str
    label_position: Point
    interpretation: str
    origin: Literal['student', 'template', 'uncertain']
    confidence: float = Field(ge=0, le=1)
    evidence: str
    ambiguity: str
    color: Optional[str] = Field(default=None, pattern=r'^#[0-9a-fA-F]{6}$')


class Sketch(Strict):
    title: str
    summary: str
    representation: str
    objects: list[Object]
    relations: list[Relation]
    uncertainties: list[str]
    omitted_details: list[str]
    simulation_readiness: Literal['qualitative_only', 'equations_visible', 'insufficient_structure']
    simulation_requirements: list[str]
    suggested_interactions: list[str]


def validate_sketch(value):
    s = Sketch.model_validate(value)
    ids = [o.id for o in s.objects] + [r.id for r in s.relations]
    if len(ids) != len(set(ids)):
        raise ValueError('All object and relation IDs must be unique')
    objects = {o.id: o for o in s.objects}
    for o in s.objects:
        b = o.bbox
        if b.x+b.width > 1000.01 or b.y+b.height > 1000.01:
            raise ValueError(f'{o.id}: bounding box exceeds image')
        if o.members and o.glyph:
            raise ValueError(f'{o.id}: group must not paint its children twice')
        if any(i not in objects or i == o.id for i in o.members):
            raise ValueError(f'{o.id}: invalid member reference')
        if len(o.members) != len(set(o.members)):
            raise ValueError(f'{o.id}: duplicate group member')
        for g in o.glyph:
            minimum = {'text': 1, 'polygon': 3}.get(g.kind, 2)
            if len(g.points) < minimum:
                raise ValueError(f'{o.id}: malformed glyph')
    def walk(id_, stack):
        if id_ in stack:
            raise ValueError('Group containment cycle')
        for child in objects[id_].members:
            walk(child, stack | {id_})
    for id_ in objects:
        walk(id_, set())
    for r in s.relations:
        if any(id_ is not None and id_ not in objects for id_ in (r.source, r.target)):
            raise ValueError(f'{r.id}: unknown object reference')
        if len(r.points) < 2:
            raise ValueError(f'{r.id}: relation needs visible endpoints')
    return s
