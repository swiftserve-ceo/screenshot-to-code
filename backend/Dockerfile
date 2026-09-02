FROM python:3.12-slim-bookworm

# Poetry 2.x — required to read the lock file (lock-version 2.1).
ENV POETRY_VERSION 2.4.2

# Install system dependencies
RUN pip install "poetry==$POETRY_VERSION"

# Set work directory
WORKDIR /app

# Copy only requirements to cache them in docker layer
COPY poetry.lock pyproject.toml /app/

# Disable the creation of virtual environments
RUN poetry config virtualenvs.create false

# Install dependencies
RUN poetry install

# Install Chromium and Linux libraries needed by Playwright screenshot previews.
RUN playwright install --with-deps chromium

# Copy the current directory contents into the container at /app
COPY ./ /app/
