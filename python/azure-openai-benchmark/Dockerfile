FROM python:3.11

WORKDIR /app
ADD benchmark/ benchmark/
ADD requirements.txt .
RUN pip install -r requirements.txt --root-user-action=ignore

# Run Uvicorn with dynamic port
CMD ["sh", "-c", "uvicorn benchmark.api:app --host 0.0.0.0 --port ${BENCHMARK_TOOL_API_PORT} --reload"]