FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY run.py .

EXPOSE 9527

# Default: one-shot scan. Use --watch --web for service mode (see docker-compose.yml).
ENTRYPOINT ["python", "run.py"]
