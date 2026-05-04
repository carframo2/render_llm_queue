import os
import time
import uuid
from threading import Lock, Event
from flask import Flask, request, jsonify

app = Flask(__name__)

jobs = {}
lock = Lock()

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "50"))
AGENT_WAIT_TIMEOUT = int(os.getenv("AGENT_WAIT_TIMEOUT", "25"))


@app.route("/bridge", methods=["POST"])
def bridge():
    """
    Endpoint que llama el navegador.
    El navegador espera aquí hasta recibir respuesta del portátil.
    """
    payload = request.get_json(force=True)

    job_id = str(uuid.uuid4())
    done_event = Event()

    job = {
        "id": job_id,
        "endpoint": payload.get("endpoint"),
        "method": payload.get("method", "GET").upper(),
        "params": payload.get("params", {}),
        "status": "pending",
        "response": None,
        "error": None,
        "created_at": time.time(),
        "done_event": done_event,
    }

    with lock:
        jobs[job_id] = job

    completed = done_event.wait(timeout=REQUEST_TIMEOUT)

    with lock:
        job = jobs.get(job_id)

    if not completed or not job:
        return jsonify({
            "ok": False,
            "error": "timeout_waiting_for_local_agent",
            "job_id": job_id,
        }), 504

    if job["status"] == "error":
        return jsonify({
            "ok": False,
            "error": job["error"],
            "job_id": job_id,
        }), 500

    return jsonify({
        "ok": True,
        "job_id": job_id,
        "response": job["response"],
    })


@app.route("/agent/next-job", methods=["GET"])
def next_job():
    """
    Endpoint que consulta el portátil.
    Hace long polling: espera hasta que haya un job pendiente.
    """
    deadline = time.time() + AGENT_WAIT_TIMEOUT

    while time.time() < deadline:
        with lock:
            for job in jobs.values():
                if job["status"] == "pending":
                    job["status"] = "claimed"

                    return jsonify({
                        "ok": True,
                        "job": {
                            "id": job["id"],
                            "endpoint": job["endpoint"],
                            "method": job["method"],
                            "params": job["params"],
                        }
                    })

        time.sleep(0.25)

    return jsonify({
        "ok": True,
        "job": None,
    })


@app.route("/agent/result", methods=["POST"])
def agent_result():
    """
    Endpoint que llama el portátil cuando ya ejecutó el endpoint local.
    """
    payload = request.get_json(force=True)

    job_id = payload.get("job_id")
    response = payload.get("response")
    error = payload.get("error")

    with lock:
        job = jobs.get(job_id)

        if not job:
            return jsonify({
                "ok": False,
                "error": "job_not_found",
            }), 404

        if error:
            job["status"] = "error"
            job["error"] = error
        else:
            job["status"] = "done"
            job["response"] = response

        job["done_event"].set()

    return jsonify({"ok": True})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        threaded=True,
    )
