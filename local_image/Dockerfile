FROM python:3.12-slim

# git: diffusers is installed from its main branch.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

# CUDA 12.8 wheels bundle the CUDA runtime and support Blackwell (sm_120); the host only
# needs the NVIDIA driver and the container toolkit. torchvision is required by the
# Qwen3-VL processor of the text encoder (not listed on the model card).
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cu128

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

# Weights live in the /models volume so rebuilding the image never re-downloads them.
ENV HF_HOME=/models/huggingface \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
