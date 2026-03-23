# Use official Python runtime
FROM python:3.11-slim

# Set workdir
WORKDIR /app

# Copy and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app
COPY . .

# Set the PORT environment variable (Cloud Run uses this)
ENV PORT 8080

# Expose the port (optional, good practice)
EXPOSE 8080

# Run the app with gunicorn on $PORT
CMD ["gunicorn", "-b", "0.0.0.0:8080", "main:app"]