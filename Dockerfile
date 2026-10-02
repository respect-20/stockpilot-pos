FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# -w 1: exactly one worker. More would start the digest scheduler (see
# start_scheduler in app.py) once per worker, and SQLite doesn't handle
# concurrent writers well either - fine for a single small shop's traffic.
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:8000", "--timeout", "60", "app:app"]
