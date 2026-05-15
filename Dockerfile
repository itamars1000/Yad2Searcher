FROM mcr.microsoft.com/playwright/python:v1.59.0-jammy

WORKDIR /app

# Configure timezone so datetime.now() and log timestamps are Israel time.
# Setting ENV TZ alone is not enough — tzdata must be installed and
# /etc/localtime must point at the zone.
ENV TZ=Asia/Jerusalem
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Command to run the application
CMD ["python", "bot_engine.py"]
