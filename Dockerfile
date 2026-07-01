FROM mirror.gcr.io/library/python:3.11-slim

WORKDIR /app

# gcc/libpq-dev — сборка psycopg; libreoffice-impress + fonts — конвертация
# PPTX → PDF (soffice --headless --convert-to pdf).
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    libreoffice-impress libreoffice-core \
    fonts-dejavu fonts-liberation \
    && rm -rf /var/lib/apt/lists/*


COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]