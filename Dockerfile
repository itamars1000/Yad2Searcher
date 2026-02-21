FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Environment variables (Can be overridden)
# ENV TELEGRAM_TOKEN=... 

# Command to run the application
CMD ["python", "bot_engine.py"]
