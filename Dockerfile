FROM mcr.microsoft.com/playwright/python:v1.60.0-jammy

WORKDIR /app

# Configure timezone so datetime.now() and log timestamps are Israel time.
# Setting ENV TZ alone is not enough — tzdata must be installed and
# /etc/localtime must point at the zone.
ENV TZ=Asia/Jerusalem
ENV DEBIAN_FRONTEND=noninteractive
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install the patched (stealthier) Chromium used by patchright.
RUN patchright install chromium

# Unbuffered stdout so logs appear immediately in `docker logs`.
ENV PYTHONUNBUFFERED=1

# Copy the rest of the application
COPY . .

# Command to run the application (patchright runs headless; HEADFUL is left unset).
CMD ["python", "bot_engine.py"]
