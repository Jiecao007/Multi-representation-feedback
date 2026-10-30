"""Project shared profile variables to their owning simulator Agent.

Profile files continue to select the same five flat operational levels. Only
the assigned variables and shared catalogue language are sent to each Agent;
the derived combination description never branches on a profile identifier.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path


CATALOGUE_PATH = Path(__file__).resolve().parent / "profile_dimensions.json"


def project_profile(resolved_profile: dict, role: str, *, catalogue: dict | None = None):
    """Return a role-scoped profile with its shared, selected-level description.

    The input must already have its selected levels expanded by resolve_profile.
    No knowledge is inferred or changed here. Composite language combines only
    variables owned by this role and adds no outcome, error or turn schedule.
    Demand contracts are conditional instructions for that role to apply to its
    actual request and saved support, not a Python classifier of student ability.
    """
    if catalogue is None:
        catalogue = json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))
    ownership = catalogue["agent_ownership"]
    if role not in ownership:
        raise ValueError("Profile role must be knowledge_model or learner.")
    dimensions = resolved_profile.get("dimensions")
    if not isinstance(dimensions, dict):
        raise ValueError("Project an expanded profile with selected dimensions.")

    selected = {}
    levels = {}
    for name in ownership[role]["dimensions"]:
        value = dimensions.get(name)
        if not isinstance(value, dict) or value.get("level") not in catalogue["dimensions"][name]["levels"]:
            raise ValueError("An assigned profile dimension lacks a supported selected level.")
        if not isinstance(value.get("operational_behavior"), dict):
            raise ValueError("Profile projection requires expanded operational definitions.")
        selected[name] = deepcopy(value)
        levels[name] = value["level"]

    projected = {key: deepcopy(resolved_profile[key]) for key in ("id", "constructed_profile")
                 if key in resolved_profile}
    projected["dimensions"] = selected
    projected["demand_contracts"] = {}
    for name, level in levels.items():
        contract = catalogue["demand_contracts"][name]
        projected["demand_contracts"][name] = {
            "demand": contract["demand"],
            "support_to_check": contract["support_to_check"],
            **deepcopy(contract["levels"][level]),
        }
    templates = catalogue["composite_prompt_templates"][role]
    description = [templates["selected_variables"].format(**levels)]
    description.extend(templates["dimension_summaries"][name][level]
                       for name, level in levels.items())
    low_representation_count = sum(levels.get(name) == "low" for name in (
        "textual_representation", "diagrammatic_representation", "coordination_translation"))
    if role == "learner" and low_representation_count > 1:
        description.append(templates["multiple_representation_needs"])
    projected["composite_characteristics"] = description

    if role == "knowledge_model":
        if "prior_knowledge" in resolved_profile:
            projected["prior_knowledge"] = deepcopy(resolved_profile["prior_knowledge"])
    else:
        projected["constructs"] = {
            "representation_ability": deepcopy(catalogue["constructs"]["representation_ability"])}
        projected["shared_communication_style"] = deepcopy(catalogue["shared_communication_style"])
    return projected
