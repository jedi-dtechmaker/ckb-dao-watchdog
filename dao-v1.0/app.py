import os
import sys
import json
import time
import queue
import math
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, Response, send_file, render_template

# Ensure the current directory is on sys.path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

import metaforo_watchdog_en as watchdog

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# In-memory storage for active and completed audit jobs
# job_id -> { "queue": Queue, "status": "running"|"completed"|"failed", "results": dict, "created_at": float }
JOBS = {}
JOBS_LOCK = threading.Lock()


def get_historical_proposals():
    """List bundled reports and web exports, including the fork's archive layout."""
    root = Path(CURRENT_DIR).parent
    folders = []
    for base in (root, Path(CURRENT_DIR)):
        for folder in sorted(base.iterdir()):
            if folder.is_dir() and (folder.name.startswith("Verification Logs")
                                    or re.match(r"^\d+(?:-|$)", folder.name)):
                folders.append(folder)
    output = Path(CURRENT_DIR) / "vote_result"
    if output.is_dir():
        folders.extend(sorted(p for p in output.iterdir() if p.is_dir()))

    known_ids = {"Fiber Link": 67302, "Pocket Node": 67494,
                 "Rosen Bridge Vote": 66568, "Verification Logs": 66568}
    proposals = {}
    for folder in folders:
        files = []
        thread_id = None
        folder_match = re.match(r"^(\d+)(?:-|$)", folder.name)
        if folder_match:
            thread_id = int(folder_match.group(1))
        title = folder.name.removeprefix("Verification Logs - ")
        thread_id = thread_id or known_ids.get(title)
        for path in sorted(folder.iterdir()):
            if not path.is_file() or path.suffix not in (".json", ".csv"):
                continue
            old = re.match(r"vote_result_(\d+)_(.+)_(\d{14})$", path.stem)
            weight = re.match(r"(.+?)_(\d+)CKB_", path.stem)
            if old:
                thread_id = int(old.group(1))
                option = old.group(2)
            else:
                option = weight.group(1) if weight else path.stem.split("_")[0]
            files.append({
                "filename": path.name,
                "rel_path": path.relative_to(root).as_posix(),
                "type": path.suffix[1:],
                "option_name": option,
                "weight": int(weight.group(2)) if weight else None,
                "size": path.stat().st_size,
            })
        if not files:
            continue
        key = thread_id if thread_id is not None else folder.name
        if key in proposals:
            proposals[key]["files"].extend(files)
        else:
            proposals[key] = {"thread_id": thread_id, "title": title,
                              "folder": folder.relative_to(root).as_posix(), "files": files}
    return list(proposals.values())


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/history", methods=["GET"])
def get_history():
    """List historical audits with their options and files."""
    try:
        proposals = get_historical_proposals()
        return jsonify({"success": True, "proposals": proposals})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/history/file", methods=["GET"])
def get_history_file():
    """Fetch parsed data from a historical JSON file."""
    rel_path = request.args.get("path")
    if not rel_path:
        return jsonify({"success": False, "error": "path parameter required"}), 400

    root = Path(CURRENT_DIR).parent.resolve()
    path = (root / rel_path).resolve()
    allowed = {f["rel_path"] for proposal in get_historical_proposals()
               for f in proposal["files"]}
    if (not path.is_relative_to(root) or rel_path not in allowed
            or not path.is_file()):
        return jsonify({"success": False, "error": "Report not found"}), 404
    normalized_path = str(path)

    # If it's a CSV download request
    if request.args.get("download") == "true" or normalized_path.endswith(".csv"):
        return send_file(normalized_path, as_attachment=True)

    try:
        with open(normalized_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify({"success": True, "data": data, "path": rel_path})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/preview", methods=["POST"])
def preview_poll():
    """Quick preview: parse URL, fetch options and weights without full on-chain query."""
    body = request.get_json(silent=True) or {}
    url_or_id = body.get("url", "").strip()

    if not url_or_id:
        return jsonify({"success": False, "error": "Please provide a Metaforo URL or Thread ID"}), 400

    try:
        if url_or_id.isdigit():
            thread_id = int(url_or_id)
        else:
            thread_id = watchdog.parse_thread_id_from_url(url_or_id)

        result = watchdog.get_poll_options(thread_id)
        if not result:
            return jsonify({
                "success": False,
                "error": f"Failed to retrieve poll options for thread #{thread_id}. Make sure the proposal exists and has active polls."
            }), 404

        options, thread_id = result
        return jsonify({
            "success": True,
            "thread_id": thread_id,
            "options": options
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def run_audit_worker(job_id, thread_id, target_option_id=None):
    """Background worker that audits the proposal and emits events to job queue."""
    job_queue = JOBS[job_id]["queue"]

    def emit(event_type, payload):
        job_queue.put({"type": event_type, "data": payload, "time": time.time()})

    try:
        emit("log", f"🐕 Watchdog started audit for thread #{thread_id}")
        dt = datetime.now().astimezone()
        offset = dt.strftime("%z")
        timestamp = dt.strftime("%Y%m%d_%H%M%S") + f"(UTC+{int(offset[:3])})"

        result = watchdog.get_poll_options(thread_id)
        if not result:
            emit("error", f"Failed to fetch poll options for thread #{thread_id}")
            JOBS[job_id]["status"] = "failed"
            return

        options, thread_id = result
        if target_option_id:
            options = [opt for opt in options if str(opt["id"]) == str(target_option_id)]
            if not options:
                emit("error", f"Target option ID {target_option_id} not found in thread #{thread_id}")
                JOBS[job_id]["status"] = "failed"
                return

        emit("poll_info", {
            "thread_id": thread_id,
            "timestamp": timestamp,
            "options": options
        })

        all_option_results = []

        for opt_idx, option in enumerate(options):
            option_id = option["id"]
            option_name = option["html"]
            option_weight = option.get("weights", 0)

            emit("log", f"\n=======================================================")
            emit("log", f"Processing option [{option_name}] (ID: {option_id}, Recorded Weight: {option_weight:,.2f} CKB)")
            emit("option_start", {
                "option_id": option_id,
                "option_name": option_name,
                "option_weight": option_weight,
                "option_index": opt_idx + 1,
                "total_options": len(options)
            })

            # Fetch vote records from Metaforo
            emit("log", f"Fetching voter list from Metaforo API...")
            voters_data = watchdog.get_all_votes(option_id)
            if voters_data is None:
                raise RuntimeError(f"Failed to fetch voters for option {option_id}")
            if not voters_data:
                emit("log", f"Option [{option_name}] has 0 voters recorded.")
                all_option_results.append({
                    "option_id": option_id,
                    "option_name": option_name,
                    "option_weight": option_weight,
                    "voters": [],
                    "export_data": []
                })
                continue

            total_voters = len(voters_data)
            emit("log", f"Found {total_voters} voters for option [{option_name}]. Now auditing on-chain deposits...")

            for v_idx, vote in enumerate(voters_data):
                user_id = vote.get("user_id")
                nickname = vote.get("name", "N/A")
                metaforo_weight = vote.get("weight", 0)

                emit("voter_progress", {
                    "option_id": option_id,
                    "voter_index": v_idx + 1,
                    "total_voters": total_voters,
                    "percent": round(((v_idx + 1) / total_voters) * 100, 1),
                    "current_voter": nickname,
                    "user_id": user_id
                })

                emit("log", f"[{v_idx + 1}/{total_voters}] Auditing {nickname} (User ID: {user_id})...")

                if not user_id:
                    vote["weight_list"] = []
                    vote["weight_calc"] = 0
                    continue

                addresses = watchdog.get_user_dao_addresses(user_id)
                if not addresses:
                    emit("log", f"  ↳ No bound Nervos DAO addresses found for {nickname}")
                    vote["weight_list"] = []
                    vote["weight_calc"] = 0
                else:
                    weight_list = []
                    total_onchain_weight = 0
                    for addr in addresses:
                        addr_weight = watchdog.get_address_onchain_weight(addr)
                        weight_list.append({"address": addr, "Weight": addr_weight})
                        total_onchain_weight += addr_weight
                        emit("log", f"  ↳ Address {addr[:12]}...{addr[-6:]}: {addr_weight:,.2f} CKB")

                    vote["weight_list"] = weight_list
                    vote["weight_calc"] = total_onchain_weight

                is_discrepancy = metaforo_weight != math.floor(vote.get("weight_calc", 0))
                diff_label = "⚠️ DISCREPANCY" if is_discrepancy else "✅ VERIFIED"
                emit("log", f"  ↳ Result: Metaforo: {metaforo_weight:,.2f} | On-Chain: {vote.get('weight_calc', 0):,.2f} [{diff_label}]")

                # Emit single voter audited event
                emit("voter_completed", {
                    "option_id": option_id,
                    "nickname": nickname,
                    "user_id": user_id,
                    "voted_at": vote.get("created_at", "N/A"),
                    "total_weight_metaforo": metaforo_weight,
                    "total_weight_onchain": math.floor(vote.get("weight_calc", 0)),
                    "need_review": is_discrepancy,
                    "weight_list": vote.get("weight_list", [])
                })

            # Format export data and save files
            export_data = []
            for vote in voters_data:
                nickname = vote.get('name', 'N/A')
                userid = vote.get('user_id')
                total_weight_metaforo = vote.get('weight', 0)
                total_weight_onchain = vote.get('weight_calc', 0)
                weight_list = vote.get('weight_list', [])
                voted_at = vote.get('created_at', 'N/A')
                if voted_at != 'N/A':
                    voted_at = f"{voted_at} (UTC+0)"

                need_review = total_weight_metaforo != math.floor(total_weight_onchain)

                if weight_list:
                    for item in weight_list:
                        address = item['address']
                        export_data.append({
                            "nickname": nickname,
                            "userid": userid,
                            "voted_at": voted_at,
                            "total weight(metaforo)": total_weight_metaforo,
                            "total weight(on chain, floored)": math.floor(total_weight_onchain),
                            "address": address,
                            "address weight(floored)": math.floor(item['Weight']),
                            "need_review": need_review,
                            "explorer_url": f"https://explorer.nervos.org/address/{address}"
                        })
                else:
                    export_data.append({
                        "nickname": nickname,
                        "userid": userid,
                        "voted_at": voted_at,
                        "total weight(metaforo)": total_weight_metaforo,
                        "total weight(on chain, floored)": math.floor(total_weight_onchain),
                        "need_review": need_review,
                        "address": "",
                        "address weight(floored)": 0,
                        "explorer_url": ""
                    })

            # Save to disk
            safe_option_name = re.sub(r'[^\w\-]', '_', option_name)
            out_dir = os.path.join(CURRENT_DIR, "vote_result", str(thread_id))
            os.makedirs(out_dir, exist_ok=True)

            json_file = f"{safe_option_name}_{option_weight}CKB_{timestamp}.json"
            csv_file = f"{safe_option_name}_{option_weight}CKB_{timestamp}.csv"
            json_path = os.path.join(out_dir, json_file)
            csv_path = os.path.join(out_dir, csv_file)

            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=4)

            import csv
            fieldnames = ["nickname", "userid", "voted_at", "total weight(metaforo)", "total weight(on chain, floored)", "⚠️need_review", "address", "address weight(floored)", "explorer_url"]
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for row in export_data:
                    csv_row = dict(row)
                    csv_row["⚠️need_review"] = csv_row.pop("need_review")
                    writer.writerow(csv_row)

            emit("log", f"Saved JSON report: vote_result/{thread_id}/{json_file}")
            emit("log", f"Saved CSV report: vote_result/{thread_id}/{csv_file}")

            all_option_results.append({
                "option_id": option_id,
                "option_name": option_name,
                "option_weight": option_weight,
                "json_rel_path": f"dao-v1.0/vote_result/{thread_id}/{json_file}",
                "csv_rel_path": f"dao-v1.0/vote_result/{thread_id}/{csv_file}",
                "export_data": export_data
            })

        emit("complete", {
            "thread_id": thread_id,
            "timestamp": timestamp,
            "options": all_option_results
        })
        emit("log", "🎉 Audit completed successfully for all options!")
        JOBS[job_id]["status"] = "completed"
        JOBS[job_id]["results"] = {
            "thread_id": thread_id,
            "timestamp": timestamp,
            "options": all_option_results
        }

    except Exception as e:
        emit("error", str(e))
        emit("log", f"❌ Error during audit: {str(e)}")
        JOBS[job_id]["status"] = "failed"


@app.route("/api/audit/start", methods=["POST"])
def start_audit():
    """Start an on-chain verification audit."""
    body = request.get_json(silent=True) or {}
    url_or_id = body.get("url", "").strip()
    target_option_id = body.get("option_id")

    if not url_or_id:
        return jsonify({"success": False, "error": "URL or Thread ID is required"}), 400

    try:
        if url_or_id.isdigit():
            thread_id = int(url_or_id)
        else:
            thread_id = watchdog.parse_thread_id_from_url(url_or_id)

        job_id = str(uuid.uuid4())
        job_queue = queue.Queue()

        with JOBS_LOCK:
            JOBS[job_id] = {
                "queue": job_queue,
                "status": "running",
                "results": None,
                "created_at": time.time()
            }

        worker_thread = threading.Thread(
            target=run_audit_worker,
            args=(job_id, thread_id, target_option_id),
            daemon=True
        )
        worker_thread.start()

        return jsonify({
            "success": True,
            "job_id": job_id,
            "thread_id": thread_id
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/audit/stream/<job_id>")
def stream_audit(job_id):
    """Server-Sent Events endpoint streaming live audit updates."""
    with JOBS_LOCK:
        job = JOBS.get(job_id)

    if not job:
        return Response("event: error\ndata: Job not found\n\n", mimetype="text/event-stream", status=404)

    def event_generator():
        q = job["queue"]
        idle_counter = 0
        while True:
            try:
                # Wait for up to 1 second for next event
                event = q.get(timeout=1.0)
                event_type = event.get("type", "message")
                data_str = json.dumps(event.get("data", {}), ensure_ascii=False)
                yield f"event: {event_type}\ndata: {data_str}\n\n"

                if event_type in ("complete", "error"):
                    break
            except queue.Empty:
                # Keep-alive heartbeat comment
                yield ": ping\n\n"
                idle_counter += 1
                if job["status"] in ("completed", "failed") and q.empty():
                    break

    return Response(event_generator(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive"
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"🐕 CKB DAO Watchdog Web UI starting on http://{host}:{port}")
    app.run(host=host, port=port, debug=False)
