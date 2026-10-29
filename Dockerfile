FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN useradd --uid 10001 --user-group --create-home bot \
    && mkdir -p /data \
    && chown -R bot:bot /data /app

USER bot

CMD ["python", "-m", "app.main"]
