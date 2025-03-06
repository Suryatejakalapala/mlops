# Use Python 3.9 slim as base image
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Copy requirements file
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ .

# Expose port for the Flask application
EXPOSE 5000

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_APP=app.py

# Use a non-root user for security
RUN adduser --disabled-password --gecos "" appuser
USER appuser

# Run the application with Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]