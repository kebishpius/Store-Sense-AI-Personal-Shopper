FROM python:3.11-slim

WORKDIR /app

# Ensure we don't write .pyc files & output is unbuffered
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install required dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Cloud Run defaults to port 8080 unless configured otherwise
EXPOSE 8080

# Command to start the application using uvicorn
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
