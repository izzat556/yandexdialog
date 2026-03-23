FROM python:3.11-slim

WORKDIR /app

# Install dependencies including gunicorn
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy app
COPY . .

# Cloud Run expects this port
ENV PORT 8080
EXPOSE 8080

# Start gunicorn server
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "app:app"]