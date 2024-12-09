# This Dockerfile is a multi-stage build. The first stage builds the frontend.
FROM node:20-slim AS frontend-builder
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
RUN corepack enable
WORKDIR /phoenix/app/
COPY ./app /phoenix/app
RUN pnpm install
RUN pnpm run build

# The second stage builds the backend.
FROM python:3.11-bullseye AS backend-builder
WORKDIR /phoenix
COPY ./src /phoenix/src
COPY ./pyproject.toml /phoenix/
COPY ./LICENSE /phoenix/
COPY ./IP_NOTICE /phoenix/
COPY ./README.md /phoenix/
COPY --from=frontend-builder /phoenix/src/phoenix/server/static/ /phoenix/src/phoenix/server/static/
# Delete symbolic links used during development.
RUN find src/ -xtype l -delete
RUN pip install --target ./env ".[container, pg]"
CMD ["bash"]