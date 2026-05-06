FROM python:latest

ARG SECRET_KEY
ARG DB_PASSWORD

ENV APP_HOME=/app

RUN pip install --no-cache-dir flask gunicorn

COPY .env /app/.env
COPY requirements.txt /app/
COPY . /app/

EXPOSE 8080

CMD ["python", "app.py"]
