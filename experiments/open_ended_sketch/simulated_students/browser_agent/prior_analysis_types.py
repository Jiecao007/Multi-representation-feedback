"""Multimodal response analysis and a deterministic, task-independent case compiler.

Analysis records observations and response-grounded knowledge hypotheses.
Compilation preserves those inferred states and checks their provenance; it does
not impose an omission-to-inability policy, solve the task, or diagnose the
original learner's latent ability. No model, browser, or file calls occur here.
"""
from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AnalysisModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FigureRegion(AnalysisModel):
    """Optional normalized region in the cited input image, not canvas geometry."""
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def region_fits_image(self):
        if self.x + self.width > 1.000001 or self.y + self.height > 1.000001:
            raise ValueError("A normalized figure region must fit inside its input image.")
        return self


class SourceEvidence(AnalysisModel):
    id: str
    source: Literal["student_text", "student_figure", "task_text", "task_figure"]
    quote: Optional[str]
    figure_index: Optional[int] = Field(ge=0)
    region: Optional[FigureRegion]
    observation: str


class ResponseObservation(AnalysisModel):
    id: str
    kind: Literal["demonstrated", "missing", "conflicting", "uncertain"]
    description: str
    evidence_ids: list[str]


class KnowledgeHypothesis(AnalysisModel):
    component_id: str
    label: str
    state: Literal["demonstrated", "partial", "not_demonstrated", "contradicted", "uncertain"]
    statement: str
    initial_limitation: str
    learning_requirement: str
    evidence_ids: list[str]
    observation_ids: list[str]
    observed_awareness: Optional[Literal[
        "unaware", "notices_incompleteness", "identifies_missing_part",
    ]]
    # Old analysis JSON remains inspectable. New compilation requires an actual
    # model inference; an absent historical field is never silently filled.
    inferred_status: Optional[Literal["known", "tentative", "unlearned"]] = None


class CrossRepresentationRelation(AnalysisModel):
    id: str
    relation: Literal["consistent", "conflicting", "uncertain"]
    description: str
    evidence_ids: list[str]


class PriorAnalysis(AnalysisModel):
    task_summary: str
    evidence: list[SourceEvidence]
    observations: list[ResponseObservation]
    knowledge_components: list[KnowledgeHypothesis]
    cross_representation: list[CrossRepresentationRelation]
    overall_uncertainty: str


class AnalysisBoundaryError(ValueError):
    """Analysis has unsupported references or cannot safely condition a learner."""


def _nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        raise AnalysisBoundaryError(label + " must be nonempty text.")


def _unique(items, key, label):
    values = [getattr(item, key) for item in items]
    for value in values:
        _nonempty(value, label + " ID")
    if len(values) != len(set(values)):
        raise AnalysisBoundaryError(label + " IDs must be unique.")
    return {getattr(item, key): item for item in items}


def _references(ids, available, label):
    if not ids or len(ids) != len(set(ids)) or not set(ids).issubset(available):
        raise AnalysisBoundaryError(label + " requires distinct existing references.")


def validate_analysis(analysis: Union[PriorAnalysis, dict], *, task_text: str,
                      response_text: str, response_figure_count: int,
                      task_figure_count: int = 0) -> PriorAnalysis:
    """Validate against original supplied text and image counts.

    Figure observations remain vision-model proposals; bounds and indices only
    verify that the referenced source exists. A text quote must be verbatim.
    Pass original task_text, including an empty string for a figure-only task.
    """
    try:
        result = analysis if isinstance(analysis, PriorAnalysis) else PriorAnalysis.model_validate(analysis)
    except Exception as exc:
        raise AnalysisBoundaryError("The analysis does not match the multimodal analysis contract.") from exc
    if not isinstance(task_text, str) or not isinstance(response_text, str):
        raise AnalysisBoundaryError("Original task and response text must be strings.")
    for count in (response_figure_count, task_figure_count):
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise AnalysisBoundaryError("Figure counts must be nonnegative integers.")
    if not task_text.strip() and not task_figure_count:
        raise AnalysisBoundaryError("A task needs text, a figure, or both.")
    if not response_text.strip() and not response_figure_count:
        raise AnalysisBoundaryError("A student response needs text, a figure, or both.")
    _nonempty(result.task_summary, "Task summary")
    evidence = _unique(result.evidence, "id", "Evidence")
    observations = _unique(result.observations, "id", "Observation")
    components = _unique(result.knowledge_components, "component_id", "Knowledge component")
    _unique(result.cross_representation, "id", "Cross-representation relation")
    if not evidence or not observations or not components:
        raise AnalysisBoundaryError("Analysis needs evidence, observations, and knowledge components.")
    for item in result.evidence:
        _nonempty(item.observation, "Evidence observation")
        if item.source.endswith("_text"):
            text = response_text if item.source == "student_text" else task_text
            if not isinstance(item.quote, str) or not item.quote.strip() or item.quote not in text:
                raise AnalysisBoundaryError("Text evidence must quote the original source verbatim.")
            if item.figure_index is not None or item.region is not None:
                raise AnalysisBoundaryError("Text evidence cannot claim an image location.")
        else:
            count = response_figure_count if item.source == "student_figure" else task_figure_count
            if item.figure_index is None or item.figure_index < 0 or item.figure_index >= count:
                raise AnalysisBoundaryError("Figure evidence must reference an existing input image.")
            if item.quote is not None:
                raise AnalysisBoundaryError("Image observations use observation text, not unverifiable text-source quotes.")
    student_evidence = {key for key, item in evidence.items() if item.source.startswith("student_")}
    if not student_evidence:
        raise AnalysisBoundaryError("Task or scaffold evidence cannot replace student-response evidence.")
    for item in result.observations:
        _nonempty(item.description, "Observation description")
        _references(item.evidence_ids, evidence, "Observation")
        if not set(item.evidence_ids) & student_evidence:
            raise AnalysisBoundaryError("A response observation must cite the student's submitted work.")
    for item in result.knowledge_components:
        for value, label in [(item.label, "Knowledge label"), (item.statement, "Knowledge statement"),
                             (item.initial_limitation, "Initial limitation"),
                             (item.learning_requirement, "Learning requirement")]:
            _nonempty(value, label)
        _references(item.evidence_ids, evidence, "Knowledge hypothesis")
        _references(item.observation_ids, observations, "Knowledge hypothesis")
        if not set(item.evidence_ids) & student_evidence:
            raise AnalysisBoundaryError("Task facts alone cannot establish a learner's knowledge or difficulty.")
        observed_evidence = {key for oid in item.observation_ids for key in observations[oid].evidence_ids}
        # Validated task citations may qualify the requested scope or scaffold.
        # The actual claim about the learner must still be supported by linked
        # observations of the student's own text/figure, not by task givens.
        if not (set(item.evidence_ids) & student_evidence).issubset(observed_evidence):
            raise AnalysisBoundaryError("Student knowledge evidence must be supported by its linked response observations.")
        if item.state == "demonstrated" and not any(
                observations[oid].kind == "demonstrated" for oid in item.observation_ids):
            raise AnalysisBoundaryError("Demonstrated knowledge needs a demonstrated response observation.")
        if item.observed_awareness is not None and not any(
                evidence[key].source == "student_text" for key in item.evidence_ids):
            raise AnalysisBoundaryError("A claim about observed gap awareness needs cited student text.")
    for item in result.cross_representation:
        _nonempty(item.description, "Cross-representation description")
        _references(item.evidence_ids, evidence, "Cross-representation relation")
        sources = {evidence[key].source for key in item.evidence_ids}
        if not {"student_text", "student_figure"}.issubset(sources):
            raise AnalysisBoundaryError("A text/figure relation needs evidence from both student modalities.")
        if item.relation in {"conflicting", "uncertain"}:
            required = set(item.evidence_ids)
            represented = any(
                component.state != "demonstrated"
                and required.issubset(component.evidence_ids)
                and any(observations[oid].kind in {"conflicting", "uncertain"}
                        and required.issubset(observations[oid].evidence_ids)
                        for oid in component.observation_ids)
                for component in result.knowledge_components
            )
            if not represented:
                raise AnalysisBoundaryError(
                    "A conflicting or uncertain text/figure relation must also condition a non-demonstrated knowledge component through a linked conflicting/uncertain observation.")
    return result


def _evidence_description(item: SourceEvidence) -> str:
    if item.source.endswith("_text"):
        return item.id + " / " + item.source + ": " + item.quote
    location = item.source + "[" + str(item.figure_index) + "]"
    if item.region is not None:
        location += " region=" + str(item.region.model_dump())
    return item.id + " / " + location + ": " + item.observation


def compile_case(analysis: Union[PriorAnalysis, dict], *, case_id: str, source_id: str,
                 task_text: str, response_text: str, response_figure_count: int,
                 task_figure_count: int = 0,
                 omission_policy: Optional[str] = None,
                 default_gap_awareness: Optional[str] = None) -> dict:
    """Compile the existing case interface without domain-specific rules.

    Each initial status comes from the analysis of the actual response, not a
    configured omission policy. Missing evidence remains uncertain; it does not
    become inability or expertise. Historical policy arguments are recognized
    only to reject them clearly instead of silently reinterpreting an old run.
    Exact submitted text is kept, without adding a solution or repair sequence.
    """
    _nonempty(case_id, "Case ID")
    _nonempty(source_id, "Source ID")
    if omission_policy is not None or default_gap_awareness is not None:
        raise AnalysisBoundaryError(
            "Configured omission or gap-awareness policies are no longer used. Infer prior knowledge from the original response.")
    result = validate_analysis(analysis, task_text=task_text, response_text=response_text,
                               response_figure_count=response_figure_count,
                               task_figure_count=task_figure_count)
    evidence = {item.id: item for item in result.evidence}
    observations = {item.id: item for item in result.observations}
    student_evidence = {key: item for key, item in evidence.items() if item.source.startswith("student_")}
    features = [{"feature_id": "F_" + key, "observation": item.observation,
                 "evidence": _evidence_description(item)} for key, item in student_evidence.items()]
    states, gaps, bindings, awareness_sources = [], [], [], []
    for item in result.knowledge_components:
        status = item.inferred_status
        if status is None:
            raise AnalysisBoundaryError(
                "This analysis predates response-inferred prior states. Reanalyze the original task and response; no default inability is applied.")
        if status == "known" and item.state != "demonstrated":
            raise AnalysisBoundaryError("Known initial knowledge requires demonstrated response evidence.")
        if item.state == "not_demonstrated" and status != "tentative":
            raise AnalysisBoundaryError(
                "An omitted or unobserved skill remains uncertain; omission alone cannot establish knowledge or inability.")
        states.append({"component_id": item.component_id, "label": item.label,
                       "status": status, "statement": item.statement,
                       "basis": "Inferred from cited original response evidence. Analysis state=" + item.state + "; inferred status=" + status + "."})
        unresolved = [observations[key] for key in item.observation_ids
                      if observations[key].kind != "demonstrated"]
        gap_ids = []
        if item.state != "demonstrated" or unresolved:
            gap_id = "G_" + item.component_id
            gap_ids.append(gap_id)
            awareness = item.observed_awareness or "unknown"
            quotes = [evidence[key].quote for key in item.evidence_ids
                      if evidence[key].source == "student_text"]
            belief = (quotes[0] if item.observed_awareness is not None and quotes else
                      "No specific belief about this gap is established by the submitted response.")
            gap_description = "; ".join(observation.description for observation in unresolved)
            if not gap_description:
                gap_description = "The submitted response does not establish this part: " + item.label + "."
            gaps.append({"gap_id": gap_id, "missing_part": gap_description,
                         "evidence": " | ".join(_evidence_description(evidence[key]) for key in item.evidence_ids),
                         "affected_components": [item.component_id], "initial_awareness": awareness,
                         "learner_belief": belief})
            awareness_sources.append({"component_id": item.component_id,
                                      "basis": "text-grounded analysis proposal" if item.observed_awareness is not None else "not established by submitted response",
                                      "value": awareness})
        limitation = item.initial_limitation
        requirement = item.learning_requirement
        bindings.append({"component_id": item.component_id,
                         "response_feature_ids": ["F_" + key for key in item.evidence_ids if key in student_evidence],
                         "response_gap_ids": gap_ids, "initial_limitation": limitation,
                         "learning_requirement": requirement})
    assumption = (
        "This is a response-inferred knowledge hypothesis, based only on the original Task and submitted Response. "
        "Preserve demonstrated understanding, partial knowledge, evidenced difficulty and uncertainty separately. "
        "Omission alone establishes neither inability nor an available method. Ability-profile levels do not add content knowledge. "
        "Gap awareness remains unknown unless the submitted student text supports it; no awareness default is imposed.")
    return {
        "id": case_id, "source_id": source_id,
        "task_text": task_text if task_text.strip() else result.task_summary,
        "initial_explanation": response_text,
        "initial_conceptual_state": {
            "constructed": True, "misconception_type": "uncertain",
            "initial_belief": response_text if response_text.strip() else "This figure is my submitted attempt.",
            "knowledge_components": states,
            "scope": "Response-inferred knowledge hypotheses, not measured traits. Follow the submitted evidence and explicit uncertainty; no additional inability or ability profile is imposed on content knowledge.",
        },
        "response_grounding": {
            "source_id": source_id, "present_features": features, "missing_parts": gaps,
            "inference_limits": "Evidence quotes and image locations refer to the actual task and response. Task/scaffold facts do not prove student knowledge. Image observations and knowledge inferences are model proposals; unresolved uncertainty stays explicit. No standard answer or repair sequence is supplied.",
        },
        "response_conditioning": {
            "source_id": source_id, "constructed": True, "assumption": assumption,
            "component_bindings": bindings,
        },
        "provenance": {
            "generated_prior": True, "analysis_format": "multimodal-response-prior-v2",
            "prior_policy": "response_inferred",
            "gap_awareness_sources": awareness_sources,
            "cross_representation": [item.model_dump() for item in result.cross_representation],
            "overall_uncertainty": result.overall_uncertainty,
            "task_summary_basis": "original supplied text" if task_text.strip() else "model summary of the given task figure; not a solution",
        },
    }
