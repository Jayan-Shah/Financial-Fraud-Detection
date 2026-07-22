FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure the start script is executable
RUN chmod +x ./start.sh

EXPOSE 8000

# Execute start.sh instead of running uvicorn directly
CMD ["./start.sh"]