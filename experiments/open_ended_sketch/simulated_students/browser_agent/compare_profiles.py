"""Freeze or run bounded, matched-context profile comparisons.

Prepare: python compare_profiles.py --dry-run --output NEW_DIRECTORY
Run approved inputs: python compare_profiles.py --live --prepared DIRECTORY --output NEW_DIRECTORY

The live mode calls only the current Knowledge Model Agent and Learner Agent.
It never operates the application, calls a Teacher, judges answers, repairs a
reply, or continues a dialogue. Two repetitions describe variability; they do
not estimate population trait effects or establish simulated-human fidelity.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
from urllib.parse import urlsplit

import matched_contexts as contexts
import student_model as model

HERE = Path(__file__).resolve().parent
FORMAT = "matched-profile-comparison-v2-simple-knowledge"


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_inventory():
    return sorted(set([*HERE.glob("*.py"), *HERE.glob("*.md"), *HERE.glob("*.json"),
                       *HERE.glob("profiles/*.json")]))


def portable_fixture(frozen, episode_dir):
    """Keep identical request bytes usable when the prepared bundle is copied."""
    value = deepcopy(frozen)
    observation = value["observation"]
    for key in ("screenshot_path",):
        observation[key] = os.path.relpath(observation[key], episode_dir)
    for kind in ("task_figures", "student_figures"):
        for figure in value["case_config"].get("provenance", {}).get(kind, []):
            relative = os.path.relpath(figure["path"], episode_dir)
            figure["path"] = relative
            figure["archived_path"] = relative
    return value


def freeze(output, *, archive=contexts.ARCHIVE, specs=None, repetitions=2,
           model_name=model.DEFAULT_MODEL, effort=model.DEFAULT_EFFORT):
    """Validate and freeze all pairs before any API client is constructed."""
    if repetitions != 2:
        raise ValueError("This registered comparison uses exactly two repetitions.")
    output = Path(output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    specs = deepcopy(contexts.SPECS if specs is None else specs)
    manifest = {"format": FORMAT, "created_at": utcnow(), "status": "prepared_no_api",
        "api_called": False, "model": model_name, "effort": effort,
        "repetitions": repetitions, "episodes": [], "sources": [], "assets": [],
        "role_call_upper_bound": len(specs) * 2 * repetitions * 2,
        "protocol": {"roles": ["KnowledgeModelAgent", "LearnerAgent"],
            "new_calls_per_episode": 2, "seed_import_calls": 0,
            "maximum_concurrent_episodes": 2,
            "cadence": "One new delivered Teacher move, then one Learner action.",
            "intervention": "P1 versus one specified target on the same saved task, knowledge state, Teacher move and full interface.",
            "seed": "Explicit fixture import through public Knowledge Agent initialization/replay methods; this is not a new model response or an empirical prior estimate.",
            "semantic_judge": False, "automatic_retries": 0,
            "limitations": "One local action and two repetitions per cell are diagnostic examples, not calibrated trait-effect estimates, long-term retention measurements, or proof of human fidelity."},
        "fixtures": specs}
    for source in source_inventory():
        relative = source.relative_to(HERE)
        target = output / "source_snapshot" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        manifest["sources"].append({"path": str(relative), "sha256": file_hash(target)})
    for spec in specs:
        frozen = contexts.materialize(spec, output / "fixtures" / spec["id"], archive)
        pair_hashes = []
        for repetition in range(1, repetitions + 1):
            for profile_id in ("P1", spec["target"]):
                episode_id = spec["id"] + "__" + profile_id + "__r" + str(repetition)
                directory = output / "episodes" / episode_id
                directory.mkdir(parents=True, exist_ok=False)
                portable = portable_fixture(frozen, directory)
                request, seed_receipts = contexts.seed_request(portable, profile_id, repetition)
                request_path = directory / "step_01_request.json"
                contexts.write_json(request_path, request)
                contexts.write_json(directory / "fixture_seed_receipts.json", {
                    "api_called": False, "kind": "authored_or_archived_fixture_import",
                    "provenance": frozen["provenance"], "receipts": seed_receipts})
                visible, screenshot, image_url = model.prepare_input(request, request_path)
                result = {"created_at": utcnow(), "api": {"called": False}, "decision": None, "error": None}
                model.run_two_agent_decision(request, visible, screenshot, image_url,
                    directory / "dry_run_response.json", model_name, effort, result,
                    client=None, dry_run=True, request_path=request_path)
                if result.get("status") != "dry_run" or result.get("api_calls"):
                    raise ValueError("Dry-run unexpectedly failed or attempted a model call.")
                contexts.write_json(directory / "dry_run_response.json", result)
                held_hash = contexts.digest(contexts.held_context(request))
                pair_hashes.append(held_hash)
                manifest["episodes"].append({"id": episode_id, "fixture_id": spec["id"],
                    "profile": profile_id, "repetition": repetition,
                    "request": str(request_path.relative_to(output)), "request_sha256": file_hash(request_path),
                    "held_context_sha256": held_hash, "pending_teacher_moves": 1,
                    "role_call_upper_bound": 2,
                    "seed_warnings": sum(len(receipt.get("warnings", receipt.get("rejected_updates", [])))
                                         for receipt in seed_receipts)})
        if len(set(pair_hashes)) != 1:
            raise ValueError("Paired profiles do not have identical held task, prior, knowledge, Teacher and UI.")
    for asset in sorted((output / "fixtures").rglob("*")):
        if asset.is_file():
            manifest["assets"].append({"path": str(asset.relative_to(output)), "sha256": file_hash(asset)})
    manifest["manifest_content_sha256"] = contexts.digest(manifest)
    contexts.write_json(output / "manifest.json", manifest)
    write_report(output, manifest, [])
    return manifest


def verify_prepared(directory):
    directory = Path(directory).expanduser().resolve()
    manifest = contexts.read_json(directory / "manifest.json")
    if manifest.get("format") != FORMAT or manifest.get("status") != "prepared_no_api":
        raise ValueError("A prepared, API-free comparison manifest is required.")
    expected = manifest["manifest_content_sha256"]
    if contexts.digest({key: value for key, value in manifest.items() if key != "manifest_content_sha256"}) != expected:
        raise ValueError("The prepared manifest was modified.")
    for source in manifest["sources"]:
        if file_hash(HERE / source["path"]) != source["sha256"]:
            raise ValueError("Current comparison runtime differs from the reviewed frozen source.")
        if file_hash(directory / "source_snapshot" / source["path"]) != source["sha256"]:
            raise ValueError("A frozen source file was modified.")
    for asset in manifest["assets"]:
        if file_hash(directory / asset["path"]) != asset["sha256"]:
            raise ValueError("A frozen fixture asset was modified.")
    held = {}
    for episode in manifest["episodes"]:
        path = directory / episode["request"]
        if file_hash(path) != episode["request_sha256"]:
            raise ValueError("A frozen episode request was modified.")
        request = contexts.read_json(path)
        actual = contexts.digest(contexts.held_context(request))
        if actual != episode["held_context_sha256"]:
            raise ValueError("A saved held context changed.")
        held.setdefault(episode["fixture_id"], set()).add(actual)
    if any(len(values) != 1 for values in held.values()):
        raise ValueError("A paired comparison contains unequal held contexts.")
    return manifest


class BoundedClient:
    """Mechanical per-episode role-call budget, with no response replacement."""
    def __init__(self, client):
        self.client, self.calls = client, 0
        self.responses = SimpleNamespace(parse=self.parse)

    def parse(self, **kwargs):
        expected = "KnowledgeMoveCheck" if self.calls == 0 else "LearnerAgentReply"
        if self.calls >= 2 or kwargs["text_format"].__name__ != expected:
            raise ValueError("Matched episode exceeded its two-role call budget or order.")
        self.calls += 1
        return self.client.responses.parse(**kwargs)


def mechanical_metrics(result):
    """Describe saved states and exact candidates; do not infer trait success."""
    reply = result.get("raw_decision") or {}
    state = result.get("learner_knowledge_model") or {}
    audit = result.get("knowledge_audit") or {}
    return {"status": result.get("status"), "role_calls": len(result.get("api_calls", [])),
        "action": reply.get("action"), "utterance": reply.get("utterance"),
        "knowledge_state": state.get("knowledge_state", {}),
        "knowledge_changed": (audit.get("before") or {}).get("knowledge_state") != state.get("knowledge_state"),
        "saved_before_learner": audit.get("check_complete", False)
            and audit.get("learner_read_state_sha256") == state.get("state_sha256"),
        "knowledge_warnings": audit.get("warnings", []),
        "semantic_entailment_checked": False,
        "qualitative_review": {"reviewed": False, "unsupported_inference": None,
            "relation_completeness": None, "support_required": None, "optional_effort": None,
            "representation_choice": None, "cross_form_link": None, "uptake_coverage": None,
            "retained_learning": "Not measured by this one-action comparison.", "notes": None}}


def run_live(prepared, output, *, client=None):
    """Explicit invocation only; callers must obtain required API authorization."""
    prepared, output = Path(prepared).resolve(), Path(output).resolve()
    manifest = verify_prepared(prepared)
    if output.exists():
        raise FileExistsError("Use a new live-output directory.")
    # No API client or credentials are loaded by freeze/verify/dry-run.
    if client is None:
        client = model.existing_client()
        endpoint = urlsplit(str(client.base_url))
        if (endpoint.scheme != "https" or endpoint.hostname != "api.openai.com"
                or endpoint.username or endpoint.password or endpoint.port not in (None, 443)):
            raise ValueError("Live comparisons require the official api.openai.com endpoint.")
        if getattr(client, "max_retries", None) != 0:
            raise ValueError("Live comparisons require SDK retries disabled.")
    shutil.copytree(prepared, output)
    def run_episode(episode):
        path = output / episode["request"]
        request = contexts.read_json(path)
        response_path = path.parent / "step_01_response.json"
        result = {"created_at": utcnow(), "api": {"called": False}, "decision": None, "error": None}
        bounded = BoundedClient(client)
        try:
            visible, screenshot, image_url = model.prepare_input(request, path)
            model.run_two_agent_decision(request, visible, screenshot, image_url, response_path,
                manifest["model"], manifest["effort"], result, client=bounded, request_path=path)
        except Exception as exc:
            # Do not serialize error bodies, headers, environment or tracebacks.
            result.update(status="comparison_episode_error", error={"type": type(exc).__name__,
                "retry_performed": False, "http_status": getattr(exc, "status_code", None)})
        contexts.write_json(response_path, result)
        metrics = mechanical_metrics(result)
        contexts.write_json(path.parent / "comparison_metrics.json", metrics)
        return {**episode, "metrics": metrics}
    results = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run_episode, episode) for episode in manifest["episodes"]]
        for future in as_completed(futures):
            completed = future.result()
            results.append(completed)
            contexts.write_json(output / "comparison_results.json", {
                "format": FORMAT, "status": "running", "episodes": results,
                "actual_role_calls": sum(item["metrics"]["role_calls"] for item in results)})
            print(json.dumps({"episode": completed["id"], "status": completed["metrics"]["status"],
                              "role_calls": completed["metrics"]["role_calls"]}), flush=True)
    order = {episode["id"]: number for number, episode in enumerate(manifest["episodes"])}
    results.sort(key=lambda episode: order[episode["id"]])
    receipt = {"format": FORMAT, "status": "completed", "created_at": utcnow(),
        "prepared_manifest_sha256": file_hash(prepared / "manifest.json"), "episodes": results,
        "actual_role_calls": sum(item["metrics"]["role_calls"] for item in results),
        "role_call_upper_bound": manifest["role_call_upper_bound"],
        "semantic_judge": False, "automatic_retries": 0}
    contexts.write_json(output / "comparison_results.json", receipt)
    write_report(output, manifest, results)
    return receipt


def write_report(directory, manifest, results):
    by_id = {item["id"]: item for item in results}
    sections = []
    for spec in manifest["fixtures"]:
        rows = []
        for episode in [item for item in manifest["episodes"] if item["fixture_id"] == spec["id"]]:
            completed = by_id.get(episode["id"])
            metrics = completed["metrics"] if completed else {}
            link = str(Path(episode["request"]).parent)
            rows.append("<tr><td>" + html.escape(episode["profile"]) + " / " + str(episode["repetition"]) +
                "</td><td>" + html.escape(metrics.get("status", "Prepared; no API call")) +
                "</td><td><pre>" + html.escape(json.dumps({key: metrics.get(key) for key in
                    ("action", "utterance", "knowledge_state", "saved_before_learner")}, ensure_ascii=False, indent=2) if completed else "") +
                '</pre><a href="' + html.escape(link) + '/step_01_request.json">Exact request</a> · <a href="' +
                html.escape(link) + '/dry_run_response.json">Dry-run projection</a>' +
                (' · <a href="' + html.escape(link) + '/comparison_metrics.json">Saved knowledge / candidate / review fields</a>' if completed else "") + "</td></tr>")
        sections.append("<section><h2>" + html.escape(spec["id"]) + "</h2><p>" + html.escape(spec["demand"]) +
            "</p><ul>" + "".join("<li>" + html.escape(question) + "</li>" for question in spec["review"]) +
            "</ul><table><tr><th>Profile / repeat</th><th>Status</th><th>Actual response and evidence</th></tr>" + "".join(rows) + "</table></section>")
    page = '<!doctype html><html lang="en"><meta charset="utf-8"><title>Matched profile contexts</title><style>body{font:16px system-ui;max-width:1200px;margin:32px auto;padding:0 20px;color:#203047}table{border-collapse:collapse;width:100%;table-layout:fixed}th,td{border:1px solid #cad3df;padding:12px;text-align:left;vertical-align:top}th:first-child{width:12%}th:nth-child(2){width:18%}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px}section{margin:36px 0}a{overflow-wrap:anywhere}</style><h1>Matched profile contexts</h1><p>Eight fixed demands compare P1 with a specified target, with two independent repetitions per cell. Task, imported or authored knowledge state, Teacher message and full interface are held fixed within each case. Fixture imports are not new model responses.</p><p>At most ' + str(manifest["role_call_upper_bound"]) + ' new model calls; only Knowledge Model Agent followed by Learner Agent. No Teacher, live browser, semantic judge, corrective retry, imposed mistake, or profile outcome is used.</p><p>State hashes and schema checks do not prove semantic entailment or strict knowledge-boundary fidelity. Review unsupported inference, relation completeness, support required, representation and optional effort from actual evidence. Retained learning is not measured by one action. Two repetitions do not establish calibrated trait effects or human fidelity.</p><p><a href="manifest.json">Frozen manifest</a></p>' + "".join(sections) + "</html>"
    (Path(directory) / "comparison_report.html").write_text(page, encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--live", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--prepared", type=Path)
    parser.add_argument("--archive", type=Path, default=contexts.ARCHIVE)
    args = parser.parse_args(argv)
    if args.dry_run:
        if args.prepared:
            parser.error("--prepared is only used with --live.")
        result = freeze(args.output, archive=args.archive)
        print(json.dumps({"status": result["status"], "episodes": len(result["episodes"]),
                          "role_call_upper_bound": result["role_call_upper_bound"], "api_called": False}))
    else:
        if not args.prepared:
            parser.error("--live requires reviewed --prepared inputs.")
        result = run_live(args.prepared, args.output)
        print(json.dumps({"status": result["status"], "actual_role_calls": result["actual_role_calls"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
