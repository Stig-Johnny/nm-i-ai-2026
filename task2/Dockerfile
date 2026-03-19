FROM python:3.11-slim

WORKDIR /app

COPY task2/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY task2/ ./task2/

ENV PORT=8080
CMD ["uvicorn", "task2.solution:app", "--host", "0.0.0.0", "--port", "8080"]
