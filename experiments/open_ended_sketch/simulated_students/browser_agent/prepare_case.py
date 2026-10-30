"""Prepare a shared response-bound case from task and student text/figures.

One analysis request prepares all selected learner profiles. No Tutor calls or
browser actions occur here. --dry-run validates and archives inputs with no API.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
from typing import Optional
from urllib.parse import urlsplit

sys.dont_write_bytecode = True
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from prior_analysis_types import PriorAnalysis, compile_case
from student_model import resolve_profile

HERE = Path(__file__).resolve().parent
EXPERIMENT = HERE.parents[1]
ROOT = HERE.parents[3]
PROMPT = HERE / "prior_analysis_prompt.md"
DEFAULT_MODEL = "gpt-6-astra"
MAX_OUTPUT_TOKENS = 7000
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 40 * 1024 * 1024
IMAGE_DETAIL = "original"
PRIOR_POLICY = "response_inferred"


class PreparationInputError(ValueError):
    pass


class TextFigureInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = ""
    figure_paths: list[str] = Field(default_factory=list)


class PreparationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    source_id: Optional[str] = None
    title: Optional[str] = None
    task: TextFigureInput
    student_response: TextFigureInput


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build_input(request: dict, request_path: Path):
    """Preserve original text and label task and student figures separately."""
    parsed = PreparationRequest.model_validate(request)
    if not parsed.case_id.strip() or (parsed.source_id is not None and not parsed.source_id.strip()):
        raise PreparationInputError("case_id and any supplied source_id must be nonempty.")
    if len(parsed.task.figure_paths) + len(parsed.student_response.figure_paths) > 8:
        raise PreparationInputError("Use at most eight task and student figures together.")
    images = []
    context = {"case_id": parsed.case_id, "source_id": parsed.source_id or parsed.case_id,
               "prior_policy": PRIOR_POLICY}
    total_bytes = 0
    for key, source in [("task", "task_figure"), ("student_response", "student_figure")]:
        part = getattr(parsed, key)
        if not part.text.strip() and not part.figure_paths:
            raise PreparationInputError(key + " needs text, a figure, or both.")
        if len(part.text) > 100000:
            raise PreparationInputError(key + " text exceeds 100,000 characters.")
        figures = []
        for index, filename in enumerate(part.figure_paths):
            if not filename.strip():
                raise PreparationInputError("Figure paths must be nonempty local paths.")
            path = Path(filename).expanduser()
            if not path.is_absolute():
                path = request_path.parent / path
            path = path.resolve()
            raw = path.read_bytes()
            if not raw or len(raw) > MAX_IMAGE_BYTES:
                raise PreparationInputError("A figure is empty or exceeds 12 MB.")
            total_bytes += len(raw)
            if total_bytes > MAX_TOTAL_IMAGE_BYTES:
                raise PreparationInputError("Combined figures exceed 40 MB.")
            with Image.open(path) as image:
                width, height = image.size
                fmt = image.format
                if fmt not in {"PNG", "JPEG", "WEBP", "GIF"} or getattr(image, "is_animated", False):
                    raise PreparationInputError("Use non-animated PNG, JPEG, WEBP, or GIF figures.")
                if width * height > 20000000:
                    raise PreparationInputError("A figure exceeds 20 million pixels.")
                image.verify()
            mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}[fmt]
            metadata = {"source": source, "figure_index": index, "width": width, "height": height,
                        "sha256": sha(raw), "mime_type": mime, "bytes": len(raw)}
            figures.append(metadata)
            images.append({**metadata, "path": str(path),
                           "data_url": "data:" + mime + ";base64," + base64.b64encode(raw).decode("ascii")})
        context[key] = {"text": part.text, "figures": figures}
    return parsed, context, images


def existing_project_client():
    """Reuse local key loading and client settings without importing Tutor code."""
    from dotenv import load_dotenv
    from openai import OpenAI
    for path in [EXPERIMENT / ".env", ROOT / ".env", ROOT / "experiments/sketch_to_interactive/.env"]:
        load_dotenv(path, override=False, interpolate=False)
    if not os.getenv("OPENAI_API_KEY"):
        raise PreparationInputError("Configure the project's existing OPENAI_API_KEY.")
    return OpenAI(timeout=600, max_retries=0)


def build_content(context, images):
    packed = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    content = [{"type": "input_text", "text": packed}]
    for image in images:
        label = ("TASK FIGURE: task givens/scaffold only, not the student's response." if image["source"] == "task_figure"
                 else "STUDENT RESPONSE FIGURE: actual submitted student work.")
        content.extend([{"type": "input_text", "text": label + " figure_index=" + str(image["figure_index"])},
                        {"type": "input_image", "image_url": image["data_url"], "detail": IMAGE_DETAIL}])
    return content


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", default="low")
    parser.add_argument("--profile", type=Path, action="append")
    parser.add_argument("--reuse-analysis", type=Path,
                        help="Reuse a response-inferred analysis only when original text/images and current analysis prompt/schema match; no new model call.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    out = args.out.expanduser().resolve()
    try:
        out.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        print(json.dumps({"status": "output_exists", "out": str(out), "api_called": False}))
        return 1
    record = {"status": "invalid_input", "created_at": datetime.now(timezone.utc).isoformat(),
              "api": {"called": False}, "error": None, "browser_actions": 0, "tutor_calls": 0}
    phase = "input"
    started = time.perf_counter()
    try:
        request_path = args.request.expanduser().resolve()
        raw_request = request_path.read_bytes()
        parsed, context, images = build_input(json.loads(raw_request), request_path)
        prompt = PROMPT.read_text(encoding="utf-8")
        profile_paths = args.profile or sorted((HERE / "profiles").glob("*.json"))
        profiles = [json.loads(p.expanduser().resolve().read_text(encoding="utf-8")) for p in profile_paths]
        if not profiles or len({p.get("id") for p in profiles}) != len(profiles):
            raise PreparationInputError("Select distinct learner profile IDs.")
        for profile in profiles:
            resolve_profile(profile, {"initial_conceptual_state": {"misconception_type": "uncertain"}})
        save(out / "request.json", json.loads(raw_request))
        save(out / "analysis.input.json", context)
        schema = PriorAnalysis.model_json_schema()
        save(out / "analysis.schema.json", schema)
        (out / "analysis.prompt.md").write_text(prompt, encoding="utf-8")
        save(out / "profiles.json", profiles)
        archived_images = []
        for image in images:
            extension = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}[image["mime_type"]]
            relative = Path("input_images") / (image["source"] + "_" + str(image["figure_index"]) + extension)
            target = out / relative
            target.parent.mkdir(exist_ok=True)
            shutil.copyfile(image["path"], target)
            archived_images.append({k: v for k, v in image.items() if k != "data_url"} | {"archived_path": relative.as_posix()})
        save(out / "analysis.images.json", archived_images)
        record.update({"case_id": parsed.case_id, "source_id": context["source_id"],
                       "prior_policy": PRIOR_POLICY,
                       "request_sha256": sha(raw_request), "prompt_sha256": sha(prompt.encode()),
                       "schema_sha256": sha(json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()),
                       "input_text_sha256": sha(json.dumps(context, ensure_ascii=False, separators=(",", ":")).encode()),
                       "selected_profiles": [p["id"] for p in profiles],
                       "modalities": {"task_text": bool(parsed.task.text.strip()), "task_figures": len(parsed.task.figure_paths),
                                      "student_text": bool(parsed.student_response.text.strip()), "student_figures": len(parsed.student_response.figure_paths)},
                       "api": {"called": False, "model_requested": args.model, "effort": args.effort,
                               "max_output_tokens": MAX_OUTPUT_TOKENS, "automatic_retries": 0, "image_detail": IMAGE_DETAIL}})
        if args.dry_run:
            record["status"] = "dry_run"
        else:
            origin_response_id = None
            if args.reuse_analysis is not None:
                phase = "analysis"
                source = args.reuse_analysis.expanduser().resolve()
                original_input = json.loads((source / "analysis.input.json").read_text(encoding="utf-8"))
                if any(original_input.get(key) != context[key] for key in ("task", "student_response")):
                    raise PreparationInputError("Saved analysis belongs to different task/response text or figures; reuse refused.")
                original_record = json.loads((source / "preparation_record.json").read_text(encoding="utf-8"))
                if original_input.get("prior_policy") != PRIOR_POLICY or original_record.get("prior_policy") != PRIOR_POLICY:
                    raise PreparationInputError(
                        "Saved analysis used an earlier imposed prior policy. Reanalyze the original task and response; legacy prior reuse refused.")
                source_prompt = (source / "analysis.prompt.md").read_bytes()
                source_schema = json.loads((source / "analysis.schema.json").read_text(encoding="utf-8"))
                if (source_prompt != prompt.encode() or source_schema != schema
                        or original_record.get("prompt_sha256") != record["prompt_sha256"]
                        or original_record.get("schema_sha256") != record["schema_sha256"]):
                    raise PreparationInputError(
                        "Saved prior analysis prompt/schema differs from the current response-inference contract; reuse refused.")
                original_analysis = (source / "analysis.json").read_bytes()
                analysis = PriorAnalysis.model_validate(json.loads(original_analysis))
                origin_response_id = original_record.get("api", {}).get("response_id")
                record["reused_analysis"] = {"source_directory": str(source), "analysis_sha256": sha(original_analysis),
                                             "original_response_id": origin_response_id,
                                             "original_status": original_record.get("status"),
                                             "new_model_call": False}
                for name in ("analysis.prompt.md", "analysis.schema.json", "analysis.response.json", "preparation_record.json"):
                    if (source / name).is_file():
                        shutil.copyfile(source / name, out / ("source_" + name))
            else:
                phase = "api"
                client = existing_project_client()
                endpoint = urlsplit(str(client.base_url))
                if endpoint.scheme != "https" or endpoint.hostname != "api.openai.com" or endpoint.username or endpoint.password:
                    raise PreparationInputError("The authorized preparation destination is https://api.openai.com.")
                record["api"].update({"called": True, "destination_origin": "https://api.openai.com"})
                response = client.responses.parse(model=args.model, instructions=prompt,
                    input=[{"role": "user", "content": build_content(context, images)}],
                    reasoning={"effort": args.effort}, max_output_tokens=MAX_OUTPUT_TOKENS,
                    store=False, text_format=PriorAnalysis)
                save(out / "analysis.response.json", response.model_dump(mode="json", warnings=False))
                usage = getattr(response, "usage", None)
                record["api"].update({"response_id": getattr(response, "id", None),
                    "request_id": getattr(response, "_request_id", None), "model_returned": getattr(response, "model", None),
                    "status": getattr(response, "status", None), "usage": usage.model_dump() if usage else None})
                phase = "analysis"
                if response.status != "completed" or response.output_parsed is None:
                    raise PreparationInputError("Analysis was incomplete or refused; no case has been generated.")
                analysis = PriorAnalysis.model_validate(response.output_parsed.model_dump() if hasattr(response.output_parsed, "model_dump") else response.output_parsed)
                origin_response_id = getattr(response, "id", None)
            save(out / "analysis.json", analysis.model_dump())
            case = compile_case(analysis, case_id=parsed.case_id, source_id=context["source_id"],
                task_text=parsed.task.text, response_text=parsed.student_response.text,
                response_figure_count=len(parsed.student_response.figure_paths), task_figure_count=len(parsed.task.figure_paths))
            if parsed.title is not None:
                case["source_title"] = parsed.title
            figures = [i for i in archived_images if i["source"] == "student_figure"]
            task_figures = [i for i in archived_images if i["source"] == "task_figure"]
            case.setdefault("provenance", {}).update({"student_figures": figures, "task_figures": task_figures,
                "preparation_request_sha256": sha(raw_request), "analysis_response_id": origin_response_id,
                "task_text_source": "provided_text" if parsed.task.text.strip() else "task_figure_summary"})
            if len(figures) == 1:
                case["provenance"]["student_crop_sha256"] = figures[0]["sha256"]
            resolved = {p["id"]: resolve_profile(p, case) for p in profiles}
            save(out / "generated_case.json", case)
            save(out / "resolved_profiles.json", resolved)
            record["status"] = "prepared"
            record["interpretation"] = "Initial knowledge is inferred from the original Task and student Response, with no configured omission-to-inability or awareness policy. This is a model hypothesis, not a verified diagnosis or profile-fidelity result. One shared analysis is reused for all selected profiles."
    except Exception as exc:
        record["status"] = {"input": "invalid_input", "api": "api_error", "analysis": "invalid_analysis"}[phase]
        record["error"] = {"type": type(exc).__name__, "phase": phase, "retry_performed": False}
        if isinstance(exc, ValidationError):
            record["error"]["validation"] = exc.errors(include_input=False, include_url=False)
        elif isinstance(exc, (PreparationInputError, ValueError)) and phase != "api":
            record["error"]["message"] = str(exc)[:1000]
    record["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    save(out / "preparation_record.json", record)
    print(json.dumps({"status": record["status"], "out": str(out), "api_called": record["api"]["called"]}))
    return 0 if record["status"] in {"prepared", "dry_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
