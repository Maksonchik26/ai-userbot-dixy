FROM python:3.12-slim

#RUN apt-get update && apt-get install -y --no-install-recommends \
#    build-essential \
#    && pip install --upgrade pip setuptools wheel \
#    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 8000

# Запуск Python-скрипта планировщика
CMD ["python", "-m", "main"]
#CMD ["pip", "freeze"]
