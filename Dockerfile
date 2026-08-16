FROM python:3.11-slim-bookworm

ARG COMPANION_MIND_COMMIT=c6a2128271532746a5570b99ce0ccdea4618db4e

LABEL org.opencontainers.image.source="https://github.com/aerenkolstein-code/llm-evaluation-lab" \
      org.opencontainers.image.description="Reproducible public-safe LLM evaluation harness" \
      org.opencontainers.image.version="0.9.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /opt/llm-evaluation-lab

COPY pyproject.toml evaluation_lab.py ./
COPY search_cup ./search_cup
COPY candidates ./candidates
COPY competitions ./competitions
COPY cases ./cases
COPY experiments ./experiments
COPY results ./results
COPY schemas ./schemas

RUN python -m pip install --no-cache-dir \
      "https://github.com/aerenkolstein-code/Companion-Mind/archive/${COMPANION_MIND_COMMIT}.tar.gz" \
    && python -m pip install --no-cache-dir -e . \
    && python -m compileall -q evaluation_lab.py search_cup \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /opt/llm-evaluation-lab

USER 10001:10001

EXPOSE 8000

ENTRYPOINT ["llm-eval"]
CMD ["--help"]
