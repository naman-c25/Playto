FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Collect static files for whitenoise
RUN python manage.py collectstatic --noinput --settings=config.settings.production || true

EXPOSE 8000

RUN chmod +x start.sh

CMD ["./start.sh"]
