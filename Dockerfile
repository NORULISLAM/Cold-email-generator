FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    chromium chromium-driver \
    tesseract-ocr poppler-utils libmagic1 curl git build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=7860 
CMD streamlit run app/main.py --server.port=${PORT:-7860} --server.address=0.0.0.0



