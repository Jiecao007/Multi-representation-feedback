"""Historical scoped-v3 reference checks; unused by the current simple runtime.

Deterministic reference/permission validation; no semantic model or retries.

These checks establish reference integrity, not entailment of arbitrary prose.
The Knowledge Model Agent remains the only interpreter of Teacher content.
"""

CONTENT_ACTIONS = {"send_message", "add_text", "edit_text", "add_connection",
                   "edit_connection", "reshape_connection", "move", "resize", "delete"}
CONTENT_FIELDS = {
    "send_message": {"text"}, "add_text": {"text"}, "edit_text": {"text", "glyphTexts"},
    "add_connection": {"from", "to", "shape", "direction", "label"},
    "edit_connection": {"from", "to", "shape", "direction", "label"},
    "reshape_connection": {"to"}, "move": {"to", "dx", "dy"},
    "resize": {"direction", "steps"}, "delete": {"id"},
    "add_object": {"label"}, "submit_revisions": {"reason"},
    "stop": {"text"},
}


def grounding_issues(reply, knowledge, observation, history):
    scopes = {scope["scope_id"] for component in knowledge.get("components", [])
              for scope in component.get("available_knowledge", [])}
    turn = knowledge.get("current_turn") or {}
    facts = {item["fact_id"] for item in turn.get("given_facts", [])}
    beliefs = {item["belief_id"] for component in knowledge.get("components", [])
               for item in component.get("provisional_beliefs", [])}
    refs = {"task"}
    refs.update("element:" + item["id"] for item in observation.get("elements", []) if item.get("id"))
    refs.update("dialog:" + item["id"] for item in observation.get("dialogs", []) if item.get("id"))
    refs.update("action:" + str(item["step"]) for item in history if "step" in item)
    issues = []
    mode = reply["response_mode"]
    permissions = turn.get("response_permissions", {})
    allowed = permissions.get("answer_mode")
    if mode == "supported_answer" and allowed in {"partial", "clarification"}:
        issues.append("A full supported answer is outside the saved current-turn permission.")
    if mode in {"provisional_attempt", "supported_action"} and not permissions.get("can_attempt", False):
        issues.append("The saved current-turn interpretation does not permit an unsupported attempt.")
    if reply["action"]["type"] in CONTENT_ACTIONS and mode in {"navigation", "stop"}:
        issues.append("A content-bearing action cannot be classified as navigation or stop.")
    if reply["action"]["type"] == "stop" and mode != "stop":
        issues.append("A stop action must use stop mode.")
    entries = reply["content_grounding"]
    action = reply["action"]
    fields = {field for field in CONTENT_FIELDS.get(action["type"], set())
              if action.get(field) is not None}
    if action["type"] == "stop":
        fields = set()  # Stopping explanation need not carry mathematical content.
    targets = {entry["target"] for entry in entries}
    missing = {"action." + field for field in fields} - targets
    if missing:
        issues.append("Ungrounded content fields: " + ", ".join(sorted(missing)))
    if fields and mode in {"navigation", "stop"}:
        issues.append("Populated content fields cannot use navigation or stop mode.")
    if mode == "stop" and action["type"] != "stop":
        issues.append("Stop mode requires a stop action.")
    if reply["action"]["type"] in CONTENT_ACTIONS and not entries:
        issues.append("A content-bearing action requires exact content grounding.")
    for entry in entries:
        if not entry["target"].startswith("action."):
            issues.append("Grounding target must identify an action field.")
        else:
            field = entry["target"].split(".", 1)[1]
            if field not in CONTENT_FIELDS.get(action["type"], set()) or action.get(field) is None:
                issues.append("Grounding target must identify a populated action field.")
        for field, valid in (("scope_ids", scopes), ("given_fact_ids", facts),
                             ("belief_ids", beliefs), ("observation_refs", refs)):
            unknown = set(entry[field]) - valid
            if unknown:
                issues.append("Unknown " + field + ": " + ", ".join(sorted(unknown)))
        if entry.get("belief_ids") and mode != "provisional_attempt":
            issues.append("A provisional belief may only support a provisional attempt.")
        if mode in {"supported_answer", "supported_action"} and not any(
                entry[field] for field in ("scope_ids", "given_fact_ids", "observation_refs")):
            issues.append("A supported claim requires a specific saved scope, given fact or observation.")
    return issues
