FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt apscheduler>=3.10.0

COPY src/ src/
COPY run.py .

# Default: one-shot scan. Override with --schedule for service mode.
ENTRYPOINT ["python", "run.py"]
