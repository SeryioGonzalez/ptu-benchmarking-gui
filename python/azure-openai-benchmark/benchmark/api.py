import asyncio
import logging
import uuid
from datetime import datetime
from enum import Enum
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from threading import Lock
from typing import Any, Optional

from .loadcmd import load
from .prometheus_exporter import start_exporter, set_metrics_provider

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    force=True
)

# Define status lifecycle
class BenchmarkStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"

# Request model
class BenchmarkRequest(BaseModel):
    api_key: str
    api_base_endpoint: str
    custom_label: str 
    deployment: str
    context_tokens: int
    max_tokens: int
    # Optional parameters with defaults
    api_version: str = "2025-01-01-preview"
    aggregation_window: Optional[int] = 60
    clients: Optional[int] = 1
    output_format: str = "jsonl"
    prevent_server_caching: bool = True
    log_request_content: bool = False
    rate: Optional[float] = 0
    retry: str = "exponential"
    # Optional parameters to None
    duration: Optional[int] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None    
    completions: Optional[int] = None

# Job model
class BenchmarkJob(BaseModel):
    id: str
    request: BenchmarkRequest
    status: BenchmarkStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Any] = None
    error: Optional[str] = None

# Initialize app and logger
logger = logging.getLogger(__name__)
app = FastAPI(title="Azure OpenAI Benchmark API")
logger.info("Starting Azure OpenAI Benchmark API")

# Only single job at a time
todo_lock = Lock()
current_job: Optional[BenchmarkJob] = None

@app.on_event("startup")
async def startup_event():
    """
    Run once when the FastAPI app starts.
    Ensures the Prometheus exporter is always up.
    """
    start_exporter()                 # exporter keeps /metrics alive
    set_metrics_provider(lambda: {}) # empty metrics until a run begins
    logger.info("Startup completed – Prometheus exporter ready")

@app.on_event("shutdown")
async def shutdown_event():
    """
    Optional: reset provider or perform clean-up.
    """
    set_metrics_provider(lambda: {})
    logger.info("Shutdown – exporter left running with empty provider")

@app.post("/benchmark", response_model=BenchmarkJob)
async def start_benchmark(req: BenchmarkRequest):
    global current_job

    logger.info("Received benchmark request")

    # 1) Validation (unchanged)
    if req.api_key is None:
        raise HTTPException(400, detail="api_key missing")

    # 2) Enqueue/cancel under the lock, then immediately release it
    with todo_lock:
        if current_job and current_job.status in (BenchmarkStatus.queued, BenchmarkStatus.running):
            logger.info("Cancelling previous benchmark job")
            current_job.status = BenchmarkStatus.failed
            current_job.completed_at = datetime.utcnow()
            current_job.error = "Canceled by new benchmark request"

        logger.info(f"Starting new benchmark job with label {req.custom_label}")
        job = BenchmarkJob(
            id=f"{req.custom_label}_{str(uuid.uuid4())}",
            request=req,
            status=BenchmarkStatus.queued,
            created_at=datetime.utcnow(),
        )
        current_job = job
        logger.info(f"Benchmark job {job.id} queued")

    # 3) Now define the background work *outside* of that with
    def run():
        # mark as running
        with todo_lock:
            logger.info(f"Running benchmark job {job.id}")
            job.status = BenchmarkStatus.running
            job.started_at = datetime.utcnow()

        try:
            # run the benchmark
            logger.info(f"Running load test for job {job.id}")
            
            result = load(req)
            # mark as completed
            with todo_lock:
                logger.info(f"Benchmark job {job.id} completed")
                job.status = BenchmarkStatus.completed
                job.completed_at = datetime.utcnow()
                job.result = result
        except Exception as e:
            # mark as failed
            with todo_lock:
                job.status = BenchmarkStatus.failed
                job.completed_at = datetime.utcnow()
                job.error = str(e)

    # 4) Fire it off
    asyncio.get_running_loop().run_in_executor(None, run)
    return job

@app.get("/benchmark", response_model=BenchmarkJob)
def get_current_benchmark():
    logger.info("Fetching current benchmark job")
    if not current_job:
        raise HTTPException(status_code=404, detail="No benchmark has been started yet")
    return current_job

@app.get("/status")
def get_status():
    logger.debug("fetching status")
    return "ok"
