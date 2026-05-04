import os
import time
import requests

RENDER_URL = os.getenv("RENDER_URL", "https://TU-APP.onrender.com").rstrip("/")
API_TOKEN = os.getenv("BRIDGE_TOKEN", "changeme")
WORKER_NAME = os.getenv("WORKER_NAME", "llm-local")

HEADERS = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Content-Type": "application/json",
}


def procesar_con_tu_llm(prompt: str, payload: dict) -> str:
    # Sustituye esto por una llamada a tu Flask local:
    # r = requests.post("http://127.0.0.1:5000/chat", json={"prompt": prompt, "session_id": "render"}, timeout=300)
    # r.raise_for_status()
    # return r.json()["respuesta_final"]
    return f"Respuesta demo al prompt: {prompt}"


while True:
    try:
        r = requests.get(
            f"{RENDER_URL}/jobs/pull",
            headers=HEADERS,
            params={"worker": WORKER_NAME},
            timeout=30,
        )
        r.raise_for_status()
        job = r.json()

        if job.get("job") is None:
            time.sleep(2)
            continue

        job_id = job["id"]
        prompt = job["prompt"]
        payload = job.get("payload") or {}

        try:
            result = procesar_con_tu_llm(prompt, payload)
            requests.post(
                f"{RENDER_URL}/jobs/{job_id}/done",
                headers=HEADERS,
                json={"result": result},
                timeout=30,
            ).raise_for_status()
        except Exception as e:
            requests.post(
                f"{RENDER_URL}/jobs/{job_id}/error",
                headers=HEADERS,
                json={"error": str(e)},
                timeout=30,
            )

    except Exception as e:
        print("Worker error:", e)
        time.sleep(5)
