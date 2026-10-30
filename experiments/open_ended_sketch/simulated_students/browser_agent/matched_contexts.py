"""Authored, immutable-context fixtures for paired learner-profile comparisons.

These are research fixtures, not a learner runtime policy or an answer judge.
Synthetic saved states are explicitly authored. Two replay states preserve the
saved local knowledge of archived model replies using the Knowledge Agent's
public initialize/check_move interfaces. Missing evidence never becomes an
unknown entry. Legacy states are imported only as explicitly labelled fixtures.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
ARCHIVE = ROOT / "outputs/simulated_students_current_20261028T202031Z_p1_p7"
FORMAT = "matched-profile-contexts-v2-simple-knowledge"
PROFILE_FILES = {
    "P1": "p1_average.json", "P2": "p2_low_motivation.json",
    "P3": "p3_low_feedback_uptake.json", "P4": "p4_low_textual_expression.json",
    "P5": "p5_low_diagrammatic_expression.json",
    "P6": "p6_low_coordination_translation.json", "P7": "p7_combined_support_needs.json",
}
SPECS = [
    {"id": "archived_positive_addition", "target": "P7", "dimension": "combined_support_needs",
     "archive_step": 3, "demand": "Direction and distance for the next positive card.",
     "review": ["Which saved known or possibly-known statement supports each claimed operation mapping?",
                "Does an unknown method remain uncertain rather than becoming an asserted inability?" ]},
    {"id": "archived_endpoint_sum", "target": "P7", "dimension": "combined_support_needs",
     "archive_step": 15, "demand": "Connect a supplied final endpoint to the requested sum.",
     "review": ["Is the endpoint-to-sum meaning supplied, positively stored, attempted, or unsupported?",
                "Does the reply distinguish the supplied endpoint from independently computing it?"]},
    {"id": "optional_check", "target": "P2", "dimension": "task_motivation",
     "demand": "Choose whether to invest in an explicitly optional check after required work is complete.",
     "teacher": "Your required route and endpoint answer are complete. You may optionally check whether both arrows match your written order; you can also stop here.",
     "review": ["Which optional effort does the selected action actually begin or decline?",
                "Is any unrequested extra work proposed? Required work is already complete."]},
    {"id": "compound_feedback", "target": "P3", "dimension": "feedback_processing",
     "demand": "Take up a compound message containing praise, a contrast, and two linked new conventions.",
     "teacher": "Your A, B, C order is right. Keep the existing A-to-B arrow. For this diagram, a solid arrow marks a route step, while a dotted line marks a comparison and is not a route step. Put a solid arrow from B to C, then place the word finish at C. Which change would you make first, and what would you leave alone?",
     "review": ["Which of the contrast, second instruction, and preserve-existing instruction is stored?",
                "Which understood parts does the Learner enact, and which remain unresolved?"]},
    {"id": "known_relational_text", "target": "P4", "dimension": "textual_representation",
     "demand": "Combine known facts into a relational explanation without a supplied sentence to copy.",
     "teacher": "Explain how the order A, B, C and the direction of both arrows show where your route finishes. Tell me how those pieces fit together.",
     "review": ["Which known relationships are expressed and which are left implicit?",
                "Does the first partial formulation stay partial or become a polished complete explanation?"]},
    {"id": "choose_visual_convention", "target": "P5", "dimension": "diagrammatic_representation",
     "demand": "Select and organize a meaning-bearing representation without exact drawing parameters.",
     "teacher": "Your written route is A, then B, then C. How would you make that order visible in the diagram? Choose a way to show it and try it.",
     "review": ["Does the action choose a convention and express its intended direction or label?",
                "What specific representational support is requested, if any? Successful supported drawing is allowed."]},
    {"id": "cross_form_discrepancy", "target": "P6", "dimension": "coordination_translation",
     "demand": "Compare a known written route against an actually reversed second arrow.",
     "teacher": "Compare your written order with the picture. Do they tell the same route? Choose one thing you would inspect or change, and explain why.",
     "review": ["Are the written order and arrow direction linked explicitly, or only described separately?",
                "Does the selected object or proposed revision address their actual correspondence?"]},
    {"id": "explicit_instruction_control", "target": "P7", "dimension": "combined_support_needs",
     "demand": "Carry out one exact local instruction; similar performance is compatible with both profiles.",
     "teacher": "Add the text finish at C using + Text. That is the only change to make now.",
     "review": ["Is the exact single-step instruction understood and locally enacted?",
                "Convergence here is expected to be possible and is not a profile-fidelity failure."]},
]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def profile(profile_id):
    return read_json(HERE / "profiles" / PROFILE_FILES[profile_id])


def synthetic_fixture(spec):
    """Common knowledge, varied demands; none of these facts comes from a real student."""
    facts = [
        ("order", "The route order is A, then B, then C."),
        ("endpoint", "C is the last marker in this route and is its endpoint."),
        ("direction", "An arrow starts at the earlier marker and points to the next marker in the route."),
    ]
    response = "Order: A, B, C. End: C, the last marker. Arrow: earlier marker to next marker."
    case = {"id": "synthetic-route", "source_id": "authored-matched-route-v1",
        "source_title": "Synthetic route fixture; no real student data",
        "task_text": "Show the route A, then B, then C, and identify where it finishes.",
        "initial_explanation": response,
        "initial_conceptual_state": {"constructed": True, "misconception_type": "uncertain",
            "initial_belief": response,
            "knowledge_components": [{"component_id": cid, "status": "known", "statement": statement}
                                     for cid, statement in facts]}}
    initial = {"knowledge_state": {
        "known": [statement for _, statement in facts],
        "unknown": [], "possibly_known": []}}
    elements = []
    for label, x in (("A", 170), ("B", 390), ("C", 610)):
        elements.append({"id": "marker_" + label.lower(), "kind": "object", "texts": [label],
                         "locator_description": "Marker " + label, "selected": False,
                         "bounds": {"x": x, "y": 330, "width": 60, "height": 60},
                         "canvas_bounds": {"x": x, "y": 330, "width": 60, "height": 60}})
    if spec["id"] != "choose_visual_convention":
        elements.append(connection("link_ab", "marker_a", "marker_b"))
    if spec["id"] in {"optional_check", "known_relational_text", "cross_form_discrepancy"}:
        first, last = (("marker_c", "marker_b") if spec["id"] == "cross_form_discrepancy"
                       else ("marker_b", "marker_c"))
        elements.append(connection("link_bc", first, last))
    editing = spec["id"] != "optional_check"
    controls = [{"id": control_id, "label": label, "disabled": disabled}
                for control_id, label, disabled in [
                    ("addNote", "+ Text", not editing), ("connect", "Connect", not editing),
                    ("rename", "Edit label / text", not editing),
                    ("beginRevision", "Begin a revision", editing),
                    ("reviewChanges", "Review changes", not editing),
                    ("hint", "I need a hint", False), ("send", "Send message", False)]]
    observation = {"task": case["task_text"], "goal": "Show and explain this local route.",
        "visible_text": "Synthetic route workspace. Written order: A, B, C. Written endpoint: C. " +
                        ("Required work complete; optional checking available." if not editing else "Revision editing is enabled."),
        "messages": [{"index": 0, "role": "assistant", "text": spec["teacher"], "error": False,
                      "show_available": False}], "controls": controls, "elements": elements,
        "handles": {"canvas_center": {"x": 410, "y": 365}}, "dialogs": [],
        "canvas": {"bounds": {"x": 40, "y": 170, "width": 740, "height": 390}},
        "status": {"draft": "Revision editing is enabled." if editing else "Required work is complete.",
                   "model_badge": "Editing" if editing else "View only"}, "stopped": False}
    return {"case_config": case, "observation": observation, "history": [],
            "initial_reply": initial, "replay_checks": [],
            "provenance": {"kind": "fully_synthetic", "real_student_data": False,
                           "known_context": "Authored fixture state, not a newly inferred prior or measured ability."}}


def connection(identifier, start, end):
    return {"id": identifier, "kind": "connection", "from": start, "to": end,
            "texts": [], "label": "", "shape": "straight", "direction": "forward", "selected": False}


def imported_knowledge_state(legacy):
    """Mechanical fixture conversion, not a new learner-knowledge inference.

    Retain only stored affirmative scopes. Historical initial_tentative notes
    represented evidence absence, so their structural provenance excludes them.
    No prose classifier tries to decide whether an arbitrary sentence is true.
    """
    state = {"known": [], "unknown": [], "possibly_known": []}
    for component in legacy.get("components", []):
        for scope in component.get("available_knowledge", []):
            basis = scope.get("basis", "")
            if basis.startswith("initial") and component.get("initial_status") != "known":
                continue
            statement = scope["statement"]
            confirmed = (basis == "initial_known" or basis in {
                "independent_application", "independently_confirmed"}
                or scope.get("evidence_basis") == "attempt_confirmation")
            bucket = "known" if confirmed else "possibly_known"
            if statement not in state[bucket]:
                state[bucket].append(statement)
        for belief in component.get("attempted_beliefs", []):
            if belief["statement"] not in state["possibly_known"]:
                state["possibly_known"].append(belief["statement"])
    # One exact statement has one category; stronger already-recorded evidence
    # takes precedence over a repeated tentative version of the same wording.
    state["possibly_known"] = [value for value in state["possibly_known"]
                               if value not in state["known"]]
    return state


def archived_fixture(spec, archive=ARCHIVE):
    source = Path(archive) / "P7" / ("step_" + str(spec["archive_step"]).zfill(2) + "_request.json")
    request = read_json(source)
    state = request["learner_knowledge_model"]
    imported = imported_knowledge_state(state)
    # Only identities of already checked pre-turn messages are replayed. The
    # imported full pre-turn state is constant across those mechanical receipts;
    # no historical intermediate state or new semantic judgment is fabricated.
    replay = [{"move": value["move"],
               "reply": {"move_id": value["move"]["move_id"],
                         "knowledge_state": deepcopy(imported)}}
              for value in state["move_checks"]]
    return {"case_config": request["case_config"], "observation": request["observation"],
            "history": request["history"], "initial_reply": {"knowledge_state": imported},
            "replay_checks": replay,
            "provenance": {"kind": "archived_saved_context", "source": str(source.resolve()),
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "archive_format": state["format"], "original_profile": "P7",
                "reinterpretation": "Explicit fixture import: initial_known or separately confirmed local statements map to known, other positive local support and attempted beliefs to possibly_known. Historical initial_tentative evidence-absence notes are excluded structurally. Unknown remains empty. Already checked message identities are registered against the constant imported pre-turn state, not presented as reconstructed intermediate learning.",
                "original_screenshot": request["observation"]["screenshot_path"]}}


def fixture(spec, archive=ARCHIVE):
    return archived_fixture(spec, archive) if "archive_step" in spec else synthetic_fixture(spec)


def frozen_asset(source, directory):
    source = Path(source).expanduser().resolve()
    data = source.read_bytes()
    name = hashlib.sha256(data).hexdigest()[:16] + source.suffix.lower()
    target = directory / name
    directory.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != data:
        raise ValueError("Frozen asset digest collision.")
    if not target.exists():
        target.write_bytes(data)
    return target


def materialize(spec, destination, archive=ARCHIVE):
    """Freeze byte-identical archived screens or render a labelled synthetic full interface."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    value = fixture(spec, archive)
    obs = value["observation"]
    original = obs.get("screenshot_path") or obs.get("screenshotPath")
    if original:
        # Copy the full historical screen for Knowledge Agent provenance; never
        # alter it or represent our new raster as the archived screenshot.
        full = frozen_asset(original, destination / "assets")
        from PIL import Image
        with Image.open(full) as image:
            size = image.size
    else:
        size = (1200, 820)
        full = destination / "synthetic_full.png"
        render_replay(obs, full, size, include_teacher=True)
    obs.pop("screenshotPath", None)
    obs["screenshot_path"] = str(full.resolve())
    obs.pop("learner_screenshot_path", None)
    provenance = value["case_config"].get("provenance", {})
    for key in ("task_figures", "student_figures"):
        for figure in provenance.get(key, []):
            candidates = [Path(figure["path"])] if figure.get("path") else []
            source = next((item for item in candidates if item.is_file()), None)
            if source is None:
                raise ValueError("An archived original Figure is unavailable.")
            figure["path"] = str(frozen_asset(source, destination / "assets").resolve())
    value["provenance"]["learner_image"] = {
        "kind": "archived_full_interface" if original else "new_synthetic_full_interface",
        "path": str(full.resolve()),
        "description": "Both agents receive the full interface, including Teacher text. Synthetic fixtures are newly rendered from authored public elements; archived images remain byte-identical copies. Chat identifies the request; saved knowledge controls available subject knowledge."}
    write_json(destination / "fixture.json", value)
    return value


def render_replay(observation, path, size=(1200, 820), *, include_teacher=False):
    """Create a fixture illustration; never edit an existing image."""
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new("RGB", size, "#f5f7fa")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 20)
        small = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 15)
    except OSError:
        font = small = ImageFont.load_default()
    draw.text((20, 15), "STRUCTURED OBSERVATION REPLAY / synthetic fixture raster", fill="#26374a", font=small)
    draw.text((20, 45), "Teacher chat provides interaction context; saved knowledge controls content knowledge.", fill="#52677d", font=small)
    synthetic = observation.get("task", "").startswith("Show the route A")
    if synthetic:
        draw.text((40, 115), "Written order: A, B, C.   Written endpoint: C.", fill="#182c41", font=font)
        draw.rectangle((40, 170, 780, 560), fill="white", outline="#bac8d8", width=2)
    elements = observation.get("elements", [])
    by_id = {item.get("id"): item for item in elements}
    centers = {}
    for item in elements:
        bounds = item.get("bounds") or item.get("screen_bounds") or {}
        if not all(key in bounds for key in ("x", "y", "width", "height")):
            continue
        x, y, width, height = [float(bounds[key]) for key in ("x", "y", "width", "height")]
        centers[item.get("id")] = (x + width / 2, y + height / 2)
        if item.get("kind") in {"connection", "relation"}:
            continue
        texts = item.get("texts") or []
        if texts:
            draw.rounded_rectangle((x, y, x + width, y + height), radius=6, fill="white", outline="#6b829c")
            draw.text((x + 4, y + 4), " ".join(str(text) for text in texts), fill="#172d43", font=font)
        elif "axis" in str(item.get("id", "")):
            draw.line((x, y + height / 2, x + width, y + height / 2), fill="#314a65", width=3)
    for item in elements:
        if item.get("kind") not in {"connection", "relation"}:
            continue
        points = item.get("points")
        transform = (observation.get("canvas") or {}).get("screen_transform")
        if points and transform:
            rendered = [(transform["a"] * point["x"] + transform["c"] * point["y"] + transform["e"],
                         transform["b"] * point["x"] + transform["d"] * point["y"] + transform["f"])
                        for point in points]
            a, b = rendered[0], rendered[-1]
            draw.line(rendered, fill="#297e8a", width=4)
            direction = ("both" if item.get("arrow_start") and item.get("arrow_end") else
                         "backward" if item.get("arrow_start") else "forward" if item.get("arrow_end") else "none")
        else:
            start = item.get("from") or item.get("source") or item.get("from_id")
            end = item.get("to") or item.get("target") or item.get("to_id")
            start = start.get("id") if isinstance(start, dict) else start
            end = end.get("id") if isinstance(end, dict) else end
            if start not in centers or end not in centers:
                continue
            a, b = centers[start], centers[end]
            draw.line((a, b), fill="#297e8a", width=4)
            direction = item.get("direction", "forward")
        import math
        angle = math.atan2(b[1] - a[1], b[0] - a[0])
        ends = [(b, angle)] if direction == "forward" else [(a, angle + math.pi)] if direction == "backward" else [(a, angle + math.pi), (b, angle)] if direction == "both" else []
        for point, orientation in ends:
            draw.polygon([point, (point[0] - 14 * math.cos(orientation - .45), point[1] - 14 * math.sin(orientation - .45)),
                          (point[0] - 14 * math.cos(orientation + .45), point[1] - 14 * math.sin(orientation + .45))], fill="#297e8a")
        label = " ".join(str(text) for text in item.get("texts", []))
        if label:
            draw.text(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - 30), label, fill="#172d43", font=small)
    if synthetic:
        y = 600
        for control in observation.get("controls", []):
            fill = "#a0a7b0" if control.get("disabled") else "#233f60"
            draw.text((40, y), control["label"] + (" (disabled)" if control.get("disabled") else ""), fill=fill, font=small)
            y += 25
    if include_teacher:
        import textwrap
        lines = textwrap.wrap(observation["messages"][-1]["text"], width=33)
        draw.text((820, 150), "Teacher", fill="#5b3d8a", font=font)
        for number, line in enumerate(lines):
            draw.text((820, 190 + 25 * number), line, fill="#333147", font=small)
    image.save(path)


def seed_request(frozen, profile_id, repeat):
    """Import saved fixture evidence mechanically, with no new semantic call."""
    import student_model as model
    from knowledge_model_agent import KnowledgeModelAgent
    from profile_prompt import project_profile
    request = {"profile": profile(profile_id), "learner_instance_id": "matched-r" + str(repeat),
        "case_config": deepcopy(frozen["case_config"]), "observation": deepcopy(frozen["observation"]),
        "history": deepcopy(frozen["history"]), "memory": None, "learner_agent_memory": None}
    resolved = model.resolve_profile(request["profile"], request["case_config"])
    owner = profile_id + ":" + request["learner_instance_id"]
    agent = KnowledgeModelAgent(request["case_config"], owner_id=owner,
        knowledge_profile=project_profile(resolved, "knowledge_model")["dimensions"]["feedback_processing"])
    seed_receipts = [agent.initialize(frozen["initial_reply"], public_initial_context={
        "student_response_text": request["case_config"].get("initial_explanation", "")})]
    for checked in frozen["replay_checks"]:
        seed_receipts.append(agent.check_move(checked["move"], checked["reply"],
            observation=request["observation"], history=request["history"]))
    request["learner_knowledge_model"] = deepcopy(agent.state)
    if len(agent.pending_moves(request["observation"], request["history"])) != 1:
        raise ValueError("A matched fixture must have exactly one pending delivered Teacher move.")
    return request, seed_receipts


def held_context(request):
    """Ignore only owner/profile bookkeeping; saved knowledge and context stay fixed."""
    knowledge = request["learner_knowledge_model"]
    return {"case_config": request["case_config"], "observation": request["observation"],
            "history": request["history"], "knowledge_state": knowledge["knowledge_state"],
            "processed_move_ids": knowledge["processed_move_ids"]}
