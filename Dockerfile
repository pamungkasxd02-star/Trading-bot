FROM python:3.12-slim-bookworm

ARG APP_UID=10001
ARG APP_GID=10001

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLCONFIGDIR=/tmp/matplotlib

RUN groupadd --gid "${APP_GID}" spotlab \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home spotlab

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip install .

COPY --chown=spotlab:spotlab config ./config
COPY --chown=spotlab:spotlab reports/baseline ./reports/baseline
COPY --chmod=0755 scripts/container-entrypoint.sh /usr/local/bin/spotlab-container

RUN mkdir -p /app/data /tmp/matplotlib \
    && chown -R spotlab:spotlab /app/data /tmp/matplotlib

USER spotlab

ENTRYPOINT ["spotlab-container"]
CMD ["paper"]
