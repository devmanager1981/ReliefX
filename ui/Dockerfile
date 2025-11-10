# Use a stable Python base image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy root-level requirements and install dependencies
# Use two separate RUN layers for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip 

# Install dependencies, including Streamlit
RUN pip install --no-cache-dir -r requirements.txt

# Copy the full project to ensure access to shared modules
# The ui/app.py file will be copied to /app/ui/app.py
COPY . .

# Set environment variable for Cloud Run port
ENV PYTHONPATH=/app
ENV PORT=8080

# CRITICAL FIX: Use the correct path (ui/app.py) AND the Shell Form 
# (no brackets) to ensure the $PORT variable is correctly expanded into an integer.
CMD streamlit run ui/app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true