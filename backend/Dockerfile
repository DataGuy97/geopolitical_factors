FROM python:3.9-slim

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application files
COPY . .

# Set environment variable for port
ENV PORT=8080
ENV PYTHONUNBUFFERED=1

# Run the application
CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT