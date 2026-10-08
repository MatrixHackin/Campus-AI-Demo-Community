FROM python:3.12-alpine
WORKDIR /app
COPY agent_runtime.py server.py /app/
EXPOSE 8080
CMD ["python", "server.py"]
