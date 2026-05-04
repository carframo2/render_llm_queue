import os
import time
import uuid
from threading import Lock
from flask import Flask, request, jsonify

app = Flask(__name__)

API_TOKEN = os.getenv("API_TOKEN", "changeme")
jobs = {}
lock = Lock()


def check_auth():
    auth = request.headers.get("Authorization", "")
    return auth == f"Bearer {API_TOKEN}"


@app.before_request
def require_auth():
    # Health público para que Render pueda comprobar que vive
    if request.path == "/health":
        return None
    if not check_auth():
        return jsonify({"error": "unauthorized"}), 401
    return None


@app.get("/")
def index():
    return jsonify({
        "service": "render-llm-queue",
        "status": "ok",
        "endpoints": [
            "GET /health",
            "POST /jobs",
            "GET /jobs/<job_id>",
            "GET /jobs/pull",
            "POST /jobs/<job_id>/done",
            "POST /jobs/<job_id>/error"
        ]
    })


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/jobs")
def create_job():
    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt", "").strip()
    payload = data.get("payload", {})

    if not prompt:
        return jsonify({"error": "Falta 'prompt'"}), 400

    job_id = str(uuid.uuid4())
    now = time.time()

    with lock:
        jobs[job_id] = {
            "id": job_id,
            "status": "pending",
            "prompt": prompt,
            "payload": payload,
            "result": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
            "worker": None,
        }

    return jsonify({"job_id": job_id, "status": "pending"}), 201


@app.get("/jobs/<job_id>")
def get_job(job_id):
    with lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "job_not_found"}), 404
        return jsonify(job)


@app.get("/jobs/pull")
def pull_job():
    worker = request.args.get("worker", "default")

    with lock:
        for job in jobs.values():
            if job["status"] == "pending":
                job["status"] = "running"
                job["worker"] = worker
                job["updated_at"] = time.time()
                return jsonify(job)

    return jsonify({"job": None})


@app.post("/jobs/<job_id>/done")
def complete_job(job_id):
    data = request.get_json(silent=True) or {}
    result = data.get("result")

    with lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "job_not_found"}), 404

        job["status"] = "done"
        job["result"] = result
        job["error"] = None
        job["updated_at"] = time.time()

    return jsonify({"job_id": job_id, "status": "done"})


@app.post("/jobs/<job_id>/error")
def fail_job(job_id):
    data = request.get_json(silent=True) or {}
    error = data.get("error", "unknown_error")

    with lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "job_not_found"}), 404

        job["status"] = "error"
        job["error"] = error
        job["updated_at"] = time.time()

    return jsonify({"job_id": job_id, "status": "error"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
