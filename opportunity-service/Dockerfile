FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 5002

CMD ["gunicorn", "--bind", "0.0.0.0:5002", "--worker-class", "gthread", \
     "--workers", "1", "--threads", "8", "--timeout", "60", \
     "--access-logfile", "-", \
     "--access-logformat", "service=opportunity-service %(t)s \"%(r)s\" %(s)s %(b)sB %(M)sms", \
     "app:app"]