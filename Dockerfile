FROM python:3.13-slim

WORKDIR /app

RUN apt-get update -y \
    && apt-get install -y --no-install-recommends ffmpeg curl unzip \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://deno.land/install.sh | sh

ENV DENO_INSTALL="/root/.deno"
ENV PATH="${DENO_INSTALL}/bin:${PATH}"

RUN curl -Ls https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

COPY pyproject.toml uv.lock ./

# Install the exact locked application dependencies first, then refresh
# yt-dlp independently so the committed uv.lock does not need regeneration.
RUN uv sync --frozen \
    && uv pip install --python .venv/bin/python --upgrade --pre "yt-dlp[default]"

COPY . .

CMD ["bash", "start"]
