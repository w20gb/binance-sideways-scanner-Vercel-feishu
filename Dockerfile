
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY wyckoff_monitor.py .

# Set timezone to Shanghai (optional, but good for logs)
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Unbuffered output for seeing logs in real-time
ENV PYTHONUNBUFFERED=1

# Run the monitor
CMD ["python", "wyckoff_monitor.py"]
