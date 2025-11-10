# Use a stable Python base image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy root-level requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir gunicorn flask

# Copy only the comm_router agent and shared modules
COPY agents/comm_router ./agents/comm_router
COPY shared ./shared

# Set environment variable for Cloud Run port
ENV PORT=8080
ENV PYTHONPATH=/app

# Set entrypoint to run Flask app via Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "agents.comm_router.main_handler:app"]
