FROM mcr.microsoft.com/playwright/python:v1.60.0-jammy

WORKDIR /app

# Configure timezone so datetime.now() and log timestamps are Israel time.
# Setting ENV TZ alone is not enough — tzdata must be installed and
# /etc/localtime must point at the zone.
ENV TZ=Asia/Jerusalem
ENV DEBIAN_FRONTEND=noninteractive
# xvfb provides a virtual display so we can run the browser headful (HEADFUL=1),
# which is much harder for anti-bot systems (PerimeterX) to fingerprint than headless.
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && apt-get update && apt-get install -y --no-install-recommends tzdata xvfb \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install the patched (stealthier) Chromium used by patchright.
RUN patchright install chromium

# Run the browser headful under a virtual display.
ENV HEADFUL=1

# Copy the rest of the application
COPY . .

# Command to run the application (wrapped in xvfb so the headful browser has a display)
CMD ["xvfb-run", "-a", "python", "bot_engine.py"]
