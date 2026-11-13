# The PhotonVox API (also the migration job and the worker). Built from api/:  docker build -f api/Dockerfile api
# The base is pinned by digest. A hashed lock of every package (as PhotonGuard's requirements.lock) comes with the first release script.
FROM python:3.12.15-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-compile -r requirements.txt
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY photonid_directory_client ./photonid_directory_client
# Unprivileged: a bug in the app must not hand out root in the container.
RUN echo 'vox:x:10001:10001:vox:/nonexistent:/usr/sbin/nologin' >> /etc/passwd && echo 'vox:x:10001:' >> /etc/group
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--proxy-headers"]
