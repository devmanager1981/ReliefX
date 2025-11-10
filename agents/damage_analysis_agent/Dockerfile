# Use a stable and lightweight Python base image
FROM python:3.12-slim

# Set working directory inside the container
WORKDIR /app

# Install dependencies early for better caching
# Copy agent-specific requirements
COPY agents/damage_analysis_agent/requirements.txt ./requirements.txt

# Use a single RUN layer for pip install with line continuation for clarity
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy the full project (agents/, shared/, ui/, etc.)
# This ensures shared modules are available to the agent
COPY . .

# Set environment variables
ENV PORT=8080
# CRITICAL: Set PYTHONPATH to /app so 'shared' and 'agents' modules can be imported
ENV PYTHONPATH=/app

# CRITICAL FIX: Use the shell form (string) for CMD.
# This ensures $PORT is substituted and the 'gunicorn' binary is correctly
# found via the shell's PATH, which often solves the "executable not found" errors
# seen in the array/exec form on certain slim/minimal base images.
CMD gunicorn --bind 0.0.0.0:$PORT agents.damage_analysis_agent.main_handler:app