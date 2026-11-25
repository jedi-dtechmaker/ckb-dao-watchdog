import os
import sys
import json
import time
import queue
import math
import re
import threading
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from flask import Flask, request, jsonify, Response, send_file, render_template

# Ensure the current directory is on sys.path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_DIR = os.path.abspath(os.environ.get("WATCHDOG_REPORT_DIR", os.path.join(CURRENT_DIR, "vote_result")))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

import metaforo_watchdog_en as watchdog

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.config['MAX_CONTENT_LENGTH'] = 4096

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
MAX_ACTIVE_JOBS = 2
JOB_RETENTION_SECONDS = 1800
JOB_START_INTERVAL_SECONDS = 5
LAST_JOB_STARTED = 0.0
REQUEST_TIMES = {"/api/preview": deque(), "/api/proposals/ongoing": deque()}
REQUEST_LIMITS = {"/api/preview": 30, "/api/proposals/ongoing": 12}
REQUEST_LOCK = threading.Lock()


@app.before_request
def limit_expensive_requests():
    if request.path not in REQUEST_TIMES:
        return None
    now = time.monotonic()
    with REQUEST_LOCK:
        timestamps = REQUEST_TIMES[request.path]
        while timestamps and timestamps[0] <= now - 60:
            timestamps.popleft()
        if len(timestamps) >= REQUEST_LIMITS[request.path]:
            return jsonify({"success": False, "error": "Too many requests. Please try again shortly."}), 429
        timestamps.append(now)
    return None


def read_thread_id():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("url"), str):
        raise ValueError("Please provide a proposal link or thread ID.")
    value = body["url"].strip()
    if not value or len(value) > 2048:
        raise ValueError("Please provide a proposal link or thread ID.")
    if value.isascii() and value.isdigit():
        if len(value) > 10:
            raise ValueError("Invalid proposal ID.")
        thread_id = int(value)
    else:
        url = urlsplit(value)
        if url.scheme not in ('http', 'https') or url.hostname != 'dao.ckb.community':
            raise ValueError("Invalid proposal link.")
        thread_id = watchdog.parse_thread_id_from_url(value)
    if not 0 < thread_id <= 2147483647:
        raise ValueError("Invalid proposal ID.")
    return thread_id, body


def get_historical_proposals():
    """Scan dao-v1.0 directory for past proposal audit folders and vote_result folder."""
    proposals = []
    
    # 1. Scan pre-packaged proposal folders like 66568-rosen-bridge
    for item in sorted(os.listdir(CURRENT_DIR)):
        item_path = os.path.join(CURRENT_DIR, item)
        if not os.path.isdir(item_path) or os.path.islink(item_path):
            continue
            
        match = re.match(r"^(\d+)-(.*)$", item)
        if match:
            thread_id = match.group(1)
            slug = match.group(2).replace("-", " ").title()
            
            # Find json and csv files
            files = []
            for f in sorted(os.listdir(item_path)):
                if (f.endswith(".json") or f.endswith(".csv")) and os.path.isfile(os.path.join(item_path, f)) and not os.path.islink(os.path.join(item_path, f)):
                    file_path = os.path.join(item_path, f)
                    is_json = f.endswith(".json")
                    
                    # Parse option name and weight if possible
                    # Example: Yes_130513771CKB_20260116_225236(UTC+8).json
                    opt_match = re.match(r"^([^_]+)_(\d+)?CKB_.*", f)
                    option_name = opt_match.group(1) if opt_match else f.split("_")[0]
                    weight = int(opt_match.group(2)) if (opt_match and opt_match.group(2)) else None
                    
                    files.append({
                        "filename": f,
                        "rel_path": f"{item}/{f}",
                        "type": "json" if is_json else "csv",
                        "option_name": option_name,
                        "weight": weight,
                        "size": os.path.getsize(file_path)
                    })
                    
            proposals.append({
                "thread_id": int(thread_id),
                "title": f"#{thread_id} - {slug}",
                "folder": item,
                "files": files
            })
            
    # 2. Scan dynamic vote_result directory
    vote_result_dir = REPORT_DIR
    if os.path.exists(vote_result_dir):
        for item in sorted(os.listdir(vote_result_dir)):
            item_path = os.path.join(vote_result_dir, item)
            if not item.isascii() or not item.isdigit() or not os.path.isdir(item_path) or os.path.islink(item_path):
                continue
                
            thread_id = item
            files = []
            for f in sorted(os.listdir(item_path)):
                if (f.endswith(".json") or f.endswith(".csv")) and os.path.isfile(os.path.join(item_path, f)) and not os.path.islink(os.path.join(item_path, f)):
                    file_path = os.path.join(item_path, f)
                    is_json = f.endswith(".json")
                    opt_match = re.match(r"^([^_]+)_(\d+)?CKB_.*", f)
                    option_name = opt_match.group(1) if opt_match else f.split("_")[0]
                    weight = int(opt_match.group(2)) if (opt_match and opt_match.group(2)) else None
                    
                    files.append({
                        "filename": f,
                        "rel_path": f"vote_result/{item}/{f}",
                        "type": "json" if is_json else "csv",
                        "option_name": option_name,
                        "weight": weight,
                        "size": os.path.getsize(file_path)
                    })
                    
            # Check if this thread_id was already added
            existing = next((p for p in proposals if str(p["thread_id"]) == str(thread_id)), None)
            if existing:
                existing["files"].extend(files)
            else:
                proposals.append({
                    "thread_id": int(thread_id) if thread_id.isdigit() else thread_id,
                    "title": f"Proposal #{thread_id} (Audited via Web)",
                    "folder": f"vote_result/{item}",
                    "files": files
                })
                
    return proposals


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/history", methods=["GET"])
def get_history():
    """List historical audits with their options and files."""
    try:
        proposals = get_historical_proposals()
        return jsonify({"success": True, "proposals": proposals})
    except Exception:
        app.logger.exception("Unable to list historical reports")
        return jsonify({"success": False, "error": "Unable to list historical reports."}), 500


@app.route("/api/proposals/ongoing", methods=["GET"])
def get_ongoing_proposals():
    """Find active polls in Metaforo's recent thread listing."""
    proposals = []
    seen = set()
    page_size = 50
    max_pages = 5
    try:
        for page in range(1, max_pages + 1):
            response = watchdog.request_with_retry(
                'get', f"{watchdog.METAFORO_API_BASE}/thread/list",
                headers=watchdog.METAFORO_HEADERS, timeout=10, max_retries=0,
                params={"page": page, "per_page": page_size, "filter": "all",
                        "category_index_id": 0, "tag_id": 0, "sort": "latest",
                        "group_name": "neurontest"},
            )
            payload = response.json()
            if payload.get("status") is not True or not isinstance(payload.get("data", {}).get("threads"), list):
                raise ValueError("Unexpected response from Metaforo")
            threads = payload["data"]["threads"]
            for thread in threads:
                thread_id = thread.get("id")
                if (thread.get("poll_status") == "on" and isinstance(thread_id, int)
                        and thread_id > 0 and thread_id not in seen):
                    seen.add(thread_id)
                    proposals.append({"thread_id": thread_id, "title": str(thread.get("title") or f"Proposal #{thread_id}")})
            if len(threads) < page_size:
                break
        return jsonify({"success": True, "proposals": proposals,
                        "limited": page == max_pages and len(threads) == page_size})
    except (watchdog.requests.exceptions.RequestException, ValueError, TypeError, AttributeError):
        return jsonify({"success": False, "error": "Unable to load proposals from Metaforo."}), 502


@app.route("/api/history/file", methods=["GET"])
def get_history_file():
    """Fetch parsed data from a historical JSON file."""
    rel_path = request.args.get("path")
    if not rel_path:
        return jsonify({"success": False, "error": "path parameter required"}), 400
        
    parts = rel_path.split('/')
    if (len(parts) == 2 and re.fullmatch(r"[0-9]+-[^/\\]+", parts[0])):
        root, subdir, filename = CURRENT_DIR, parts[0], parts[1]
    elif len(parts) == 3 and parts[0] == 'vote_result' and re.fullmatch(r"[0-9]+", parts[1]):
        root, subdir, filename = REPORT_DIR, parts[1], parts[2]
    else:
        return jsonify({"success": False, "error": "Access denied"}), 403
    if not filename or filename in ('.', '..') or '\\' in filename or not filename.endswith(('.json', '.csv')):
        return jsonify({"success": False, "error": "Access denied"}), 403
    folder = Path(root) / subdir
    file_path = folder / filename
    if folder.is_symlink() or file_path.is_symlink() or file_path.resolve().parent != folder.resolve():
        return jsonify({"success": False, "error": "Access denied"}), 403
    if not file_path.is_file():
        return jsonify({"success": False, "error": "File not found"}), 404

    # If it's a CSV download request
    if request.args.get("download") == "true" or file_path.suffix == ".csv":
        return send_file(file_path, as_attachment=True)

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify({"success": True, "data": data, "path": rel_path})
    except (OSError, ValueError):
        app.logger.exception("Unable to read report")
        return jsonify({"success": False, "error": "Unable to read report."}), 500


@app.route("/api/preview", methods=["POST"])
def preview_poll():
    """Quick preview: parse URL, fetch options and weights without full on-chain query."""
    try:
        thread_id, _ = read_thread_id()
            
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
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Please provide a valid proposal link or thread ID."}), 400
    except Exception:
        app.logger.exception("Unable to inspect proposal")
        return jsonify({"success": False, "error": "Unable to inspect proposal."}), 502


def run_audit_worker(job_id, thread_id, target_option_id=None):
    """Background worker that audits the proposal and emits events to job queue."""
    job_queue = JOBS[job_id]["queue"]
    
    def emit(event_type, payload):
        event = {"type": event_type, "data": payload, "time": time.time()}
        try:
            job_queue.put_nowait(event)
        except queue.Full:
            try:
                job_queue.get_nowait()
            except queue.Empty:
                pass
            job_queue.put_nowait(event)

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
                raise RuntimeError("Could not retrieve the voter list from Metaforo.")
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
                    raise RuntimeError("A voter record is missing its user ID.")

                addresses = watchdog.get_user_dao_addresses(user_id, strict=True)
                if not addresses:
                    emit("log", f"  ↳ No bound Nervos DAO addresses found for {nickname}")
                    vote["weight_list"] = []
                    vote["weight_calc"] = 0
                else:
                    weight_list = []
                    total_onchain_weight = 0
                    for addr in addresses:
                        addr_weight = watchdog.get_address_onchain_weight(addr, strict=True)
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
            out_dir = os.path.join(REPORT_DIR, str(thread_id))
            os.makedirs(out_dir, exist_ok=True)
            
            json_file = f"{safe_option_name}_{option_weight}CKB_{timestamp}_{job_id[:8]}.json"
            csv_file = f"{safe_option_name}_{option_weight}CKB_{timestamp}_{job_id[:8]}.csv"
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
                "json_rel_path": f"vote_result/{thread_id}/{json_file}",
                "csv_rel_path": f"vote_result/{thread_id}/{csv_file}",
                "export_data": export_data
            })

        emit("complete", {
            "thread_id": thread_id,
            "timestamp": timestamp,
            "options": all_option_results
        })
        emit("log", "🎉 Audit completed successfully for all options!")
        JOBS[job_id]["status"] = "completed"
        
    except Exception:
        app.logger.exception("Audit failed for job %s", job_id)
        emit("error", "Audit could not be completed. Please try again.")
        JOBS[job_id]["status"] = "failed"
    finally:
        JOBS[job_id]["finished_at"] = time.monotonic()


@app.route("/api/audit/start", methods=["POST"])
def start_audit():
    """Start an on-chain verification audit."""
    global LAST_JOB_STARTED
    try:
        thread_id, body = read_thread_id()
        target_option_id = body.get("option_id")
        if target_option_id is not None and (not str(target_option_id).isascii() or not str(target_option_id).isdigit() or len(str(target_option_id)) > 10):
            raise ValueError("Invalid option ID")
        job_id = str(uuid.uuid4())
        job_queue = queue.Queue(maxsize=1000)
        
        with JOBS_LOCK:
            now = time.monotonic()
            for old_id, job in list(JOBS.items()):
                if job.get("finished_at") is not None and now - job["finished_at"] > JOB_RETENTION_SECONDS:
                    del JOBS[old_id]
            completed = [(old_id, job) for old_id, job in JOBS.items() if job.get("finished_at") is not None and not job["streaming"]]
            for old_id, _ in sorted(completed, key=lambda item: item[1]["finished_at"])[:-19]:
                del JOBS[old_id]
            if sum(job["status"] == "running" for job in JOBS.values()) >= MAX_ACTIVE_JOBS:
                return jsonify({"success": False, "error": "The auditor is busy. Please try again when an audit finishes."}), 429
            if now - LAST_JOB_STARTED < JOB_START_INTERVAL_SECONDS:
                return jsonify({"success": False, "error": "Please wait a few seconds before starting another audit."}), 429
            JOBS[job_id] = {
                "queue": job_queue,
                "status": "running",
                "results": None,
                "created_at": time.time(),
                "streaming": False,
            }
            LAST_JOB_STARTED = now
            
        worker_thread = threading.Thread(
            target=run_audit_worker,
            args=(job_id, thread_id, target_option_id),
            daemon=True
        )
        try:
            worker_thread.start()
        except RuntimeError:
            with JOBS_LOCK:
                del JOBS[job_id]
            raise
        
        return jsonify({
            "success": True,
            "job_id": job_id,
            "thread_id": thread_id
        })
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Please provide a valid proposal link or thread ID."}), 400
    except Exception:
        app.logger.exception("Unable to start audit")
        return jsonify({"success": False, "error": "Unable to start audit. Please try again."}), 500


@app.route("/api/audit/stream/<job_id>")
def stream_audit(job_id):
    """Server-Sent Events endpoint streaming live audit updates."""
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job and job["streaming"]:
            return Response("Stream already connected", status=409)
        if job:
            job["streaming"] = True

    if not job:
        return Response("event: error\ndata: Job not found\n\n", mimetype="text/event-stream", status=404)

    def event_generator():
        q = job["queue"]
        try:
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
                if job["status"] in ("completed", "failed") and q.empty():
                    break
        finally:
            with JOBS_LOCK:
                job["streaming"] = False

    return Response(event_generator(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive"
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"🐕 CKB DAO Watchdog Web UI starting on http://{host}:{port}")
    app.run(host=host, port=port, debug=False)
