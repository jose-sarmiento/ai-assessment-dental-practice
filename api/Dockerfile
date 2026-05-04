FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libxcb1 \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api/app ./app
COPY api/migrations ./migrations
COPY api/setup.py api/ask.py api/agent.py .
COPY mock_data ./mock_data

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
