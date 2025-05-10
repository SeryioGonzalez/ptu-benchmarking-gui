import os
import time
import requests
from requests.exceptions import HTTPError

# Configuration
BASE_URL = "http://localhost:8000"
POLL_INTERVAL = 5  # seconds

# Helper to make POST requests
def call_api(path: str, payload: dict) -> dict:
    url = f"{BASE_URL.rstrip('/')}/{path.lstrip('/')}"
    headers = {"Content-Type": "application/json"}
    resp = requests.post(url, json=payload, headers=headers)
    try:
        resp.raise_for_status()
    except HTTPError:
        print(f"POST {url} -> {resp.status_code}")
        print("Response body:", resp.text)
        raise
    return resp.json()

# Helper to GET the current benchmark
def get_status() -> dict:
    url = f"{BASE_URL.rstrip('/')}/benchmark"
    resp = requests.get(url)
    try:
        resp.raise_for_status()
    except HTTPError:
        print(f"GET {url} -> {resp.status_code}")
        print("Response body:", resp.text)
        raise
    return resp.json()

if __name__ == "__main__":
    # Define your benchmark parameters
    benchmark_payload = {
        "api_key": "f23ed9e95aa84102940416d101141762",
        "api_base_endpoint": "https://sergioazopenai.openai.azure.com/",
        "deployment": "gpt-4o-2024-11-20",
        "api_version": "2025-01-01-preview",
        "context_tokens": 1000,
        "max_tokens": 200,
        "rate": 0,
        "duration": 30,
        "custom_label": "test"
    }

    # 1) Start a new benchmark (cancels any previous)
    print("Starting benchmark…")
    job = call_api("benchmark", benchmark_payload)
    job_id = job["id"]
    print(f"Benchmark queued (ID: {job_id}) — status = {job['status']}")
"""
    # 2) Poll for status until completion or failure
    while True:
        status = get_status()
        print(f"[{time.strftime('%X')}] Status = {status['status']}")
        if status["status"] in ("completed", "failed"):
            break
        time.sleep(POLL_INTERVAL)

    # 3) Final result or error
    if status["status"] == "completed":
        print("✅ Benchmark completed!")
        print("Result:", status.get("result"))
    else:
        print("❌ Benchmark failed:")
        print(status.get("error"))
"""