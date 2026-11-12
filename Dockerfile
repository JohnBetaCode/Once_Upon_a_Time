FROM python:3.12-slim

WORKDIR /workspace

# The PDF export bundles its own fonts (app/assets/fonts); these supply the glyphs they lack:
# DejaVu Sans for Cyrillic, Greek and symbols, WenQuanYi Micro Hei for Chinese, Japanese and Korean.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core fonts-wqy-microhei \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY config/ config/

EXPOSE 8501

CMD ["streamlit", "run", "app/main.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
