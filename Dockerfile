FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8000
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD gunicorn -k eventlet -w 1 app:app --bind 0.0.0.0:$PORT
