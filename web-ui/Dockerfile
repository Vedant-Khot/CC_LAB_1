FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY web-ui/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY web-ui/app.py ./app.py
COPY web-ui/static ./static

# the load generator lives in the repo, so the dashboard and the graded
# workload runs share one implementation instead of two copies of it
COPY loadtest/loadtest.py ./loadtest/loadtest.py

EXPOSE 8080

# Threaded so the page keeps polling /api/overview while a workload runs.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--worker-class", "gthread", \
     "--workers", "1", "--threads", "8", "--timeout", "300", \
     "--access-logfile", "-", \
     "--access-logformat", "service=web-ui %(t)s \"%(r)s\" %(s)s %(b)sB %(M)sms", \
     "app:app"]