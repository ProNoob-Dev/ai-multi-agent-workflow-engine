FROM python:3.12-slim

WORKDIR /app

# System deps: none beyond the standard library (no browsers needed in the image).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data ./data
COPY scripts ./scripts

ENV PORT=8000
EXPOSE 8000

# The JSON store and SQLite checkpoints live in ./data (mounted as a volume in compose).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
