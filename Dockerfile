FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

RUN python -c "from facenet_pytorch import InceptionResnetV1; InceptionResnetV1(pretrained='vggface2')" || true

COPY . .

EXPOSE 8000

CMD ["sh","-c","gunicorn main:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:${PORT:-8000} --workers 1 --timeout 300 --preload"]
# # Use a slim Python image
# FROM python:3.11-slim

# # Set environment variables
# ENV PYTHONDONTWRITEBYTECODE 1
# ENV PYTHONUNBUFFERED 1

# # Set work directory
# WORKDIR /app

# # Install system dependencies (needed for OpenCV and some build tools)
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     build-essential \
#     libgl1 \
#     libglib2.0-0 \
#     ffmpeg \
#     && rm -rf /var/lib/apt/lists/*

# # Copy requirements file first to leverage Docker cache
# COPY requirements.txt .

# # Install Python dependencies
# # We install torch and torchvision with the CPU index URL to significantly reduce image size
# RUN pip install --no-cache-dir --upgrade pip && \
#     pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu && \
#     pip install --no-cache-dir -r requirements.txt

# # Pre-download the face recognition model weights at BUILD time so the
# # container never downloads them at startup (which caused 99.9% log spam
# # and Railway's rate limit → 502 Bad Gateway).
# RUN python -c "from facenet_pytorch import InceptionResnetV1; InceptionResnetV1(pretrained='vggface2')" 2>/dev/null || true

# # Copy project files
# COPY . .

# # Expose the port Railway injects via $PORT (defaults to 8080)
# EXPOSE 8080

# # Use gunicorn with uvicorn workers for production stability.
# # --timeout 120 prevents 502s when the face model loads on first request.
# CMD sh -c "gunicorn main:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:${PORT:-8080} --workers 1 --timeout 120 --log-level warning"
