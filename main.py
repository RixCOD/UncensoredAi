"""
main.py
-------
Flask backend serving the dashboard (index.html), AND the single
entrypoint for the whole pipeline.

Just run `python main.py` -- it will, in a background thread:
  1. cv2json.py   (skipped if cv.json already exists)
  2. search.py    (always re-run, to pick up fresh listings)
  3. fillform.py  (always run, to process any new rows in apply.json)
and then serve the dashboard at http://localhost:5000 the whole time,
so you can watch progress live instead of waiting for it to finish.

Set RUN_PIPELINE=0 as an env var if you just want the dashboard
without kicking off a new pipeline run (e.g. you already ran the
steps manually and just want to view results).

You can also re-trigger the pipeline anytime from the dashboard's
"Run Pipeline" button, which hits POST /api/run-pipeline.
"""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from flask import Flask, jsonify, render_template, request

CV_PDF_PATH = Path("cv.pdf")
CV_JSON_PATH = Path("cv.json")
APPLY_JSON_PATH = Path("apply.json")
DONE_APPLY_JSON_PATH = Path("doneapply.json")
PIPELINE_LOG_PATH = Path("pipeline.log")

PYTHON = sys.executable  # use the same interpreter main.py is running under

app = Flask(__name__, template_folder=".", static_folder=".", static_url_path="")

# ---- Pipeline state (shared across the background thread + Flask) ---------

pipeline_lock = threading.Lock()
pipeline_state = {
    "running": False,
    "current_step": None,   # "cv2json" | "search" | "fillform" | None
    "steps_done": [],       # list of {"step": ..., "ok": bool}
    "error": None,
}


def load_json(path: Path, default):
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return default


def run_step(step_name: str, script: str) -> bool:
    """Runs one pipeline script as a subprocess, streaming its output into
    pipeline.log. Returns True on success (exit code 0)."""
    with pipeline_lock:
        pipeline_state["current_step"] = step_name

    with open(PIPELINE_LOG_PATH, "a", encoding="utf-8") as log:
        log.write(f"\n=== {step_name} ({script}) starting ===\n")
        log.flush()
        try:
            result = subprocess.run(
                [PYTHON, script],
                stdout=log,
                stderr=subprocess.STDOUT,
                cwd=str(Path(__file__).parent),
            )
            ok = result.returncode == 0
        except Exception as e:
            log.write(f"[main] failed to launch {script}: {e}\n")
            ok = False
        log.write(f"=== {step_name} finished (ok={ok}) ===\n")

    with pipeline_lock:
        pipeline_state["steps_done"].append({"step": step_name, "ok": ok})
    return ok


def run_pipeline():
    with pipeline_lock:
        if pipeline_state["running"]:
            return  # already running, don't start a second one
        pipeline_state["running"] = True
        pipeline_state["current_step"] = None
        pipeline_state["steps_done"] = []
        pipeline_state["error"] = None

    try:
        # Step 1: cv2json -- skip if cv.json already exists (no need to
        # re-parse the CV every single run).
        if not CV_JSON_PATH.exists():
            if not CV_PDF_PATH.exists():
                raise RuntimeError(
                    f"{CV_PDF_PATH} not found -- place your CV there before running."
                )
            if not run_step("cv2json", "cv2json.py"):
                raise RuntimeError("cv2json.py failed -- check pipeline.log")
        else:
            with pipeline_lock:
                pipeline_state["steps_done"].append({"step": "cv2json", "ok": True, "skipped": True})

        # Step 2: search -- scrape fresh listings into apply.json.
        if not run_step("search", "search.py"):
            raise RuntimeError("search.py failed -- check pipeline.log")

        # Step 3: fillform -- process apply.json into doneapply.json.
        if not run_step("fillform", "fillform.py"):
            raise RuntimeError("fillform.py failed -- check pipeline.log")

    except Exception as e:
        with pipeline_lock:
            pipeline_state["error"] = str(e)
    finally:
        with pipeline_lock:
            pipeline_state["running"] = False
            pipeline_state["current_step"] = None


# ---- Routes -----------------------------------------------------------------

@app.route("/")
def dashboard():
    return render_template("index.html")


@app.route("/api/stats")
def stats():
    total_found = load_json(APPLY_JSON_PATH, [])
    done = load_json(DONE_APPLY_JSON_PATH, [])

    submitted = [d for d in done if d.get("status") == "submitted"]
    pending = [d for d in done if d.get("status") == "filled_pending_review"]
    failed = [d for d in done if d.get("status") == "failed"]

    return jsonify({
        "total_found": len(total_found),
        "total_processed": len(done),
        "submitted": len(submitted),
        "pending_review": len(pending),
        "failed": len(failed),
    })


@app.route("/api/applied")
def applied():
    done = load_json(DONE_APPLY_JSON_PATH, [])
    return jsonify(list(reversed(done)))  # most recent first


@app.route("/api/pipeline-status")
def pipeline_status():
    with pipeline_lock:
        return jsonify(dict(pipeline_state))


@app.route("/api/run-pipeline", methods=["POST"])
def trigger_pipeline():
    with pipeline_lock:
        already_running = pipeline_state["running"]
    if already_running:
        return jsonify({"started": False, "reason": "already running"}), 409

    threading.Thread(target=run_pipeline, daemon=True).start()
    return jsonify({"started": True})


if __name__ == "__main__":
    if os.environ.get("RUN_PIPELINE", "1") != "0":
        threading.Thread(target=run_pipeline, daemon=True).start()
    # use_reloader=False so the pipeline thread doesn't get started twice
    # by Flask's debug-mode auto-reloader.
    app.run(debug=True, port=5000, use_reloader=False)