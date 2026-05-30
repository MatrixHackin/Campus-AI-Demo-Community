FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_INDEX_URL=https://repo.huaweicloud.com/repository/pypi/simple \
    PIP_TRUSTED_HOST=repo.huaweicloud.com \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements-ssh-gateway.txt .
RUN pip install --no-cache-dir --retries 10 -r requirements-ssh-gateway.txt

COPY app/__init__.py ./app/
COPY app/core ./app/core
COPY app/services/__init__.py ./app/services/
COPY app/services/ssh_gateway_service.py ./app/services/
COPY app/api/__init__.py ./app/api/
COPY app/api/routes/__init__.py ./app/api/routes/
COPY app/api/routes/ssh_gateway.py ./app/api/routes/
COPY app/ssh_gateway_runtime.py ./app/
COPY app/ssh_gateway_main.py ./app/

EXPOSE 8080 2222

CMD ["uvicorn", "app.ssh_gateway_main:app", "--host", "0.0.0.0", "--port", "8080"]
