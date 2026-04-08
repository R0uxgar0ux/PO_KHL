FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install \
    --no-cache-dir \
    --retries 10 \
    --timeout 60 \
    --index-url "${PIP_INDEX_URL}" \
    -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["python", "app.py"]
