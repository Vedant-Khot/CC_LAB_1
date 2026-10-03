FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 5001

# 1 worker keeps the in-memory store coherent; threads give concurrency.
CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--worker-class", "gthread", \
     "--workers", "1", "--threads", "8", "--timeout", "60", \
     "--access-logfile", "-", \
     "--access-logformat", "service=registration-service %(t)s \"%(r)s\" %(s)s %(b)sB %(M)sms", \
     "app:app"]