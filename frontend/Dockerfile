FROM node:22-bullseye-slim

# Set the working directory in the container
WORKDIR /app

# Enable the pinned pnpm from package.json's "packageManager" field.
RUN corepack enable

# Skip the Puppeteer browser download (not needed for the dev server).
ENV PUPPETEER_SKIP_DOWNLOAD=true

# Copy the manifest + lockfile first so the install layer is cached.
COPY package.json pnpm-lock.yaml /app/

# Install dependencies from the lockfile.
RUN pnpm install --frozen-lockfile

# Copy the rest of the frontend source.
COPY ./ /app/

# Expose the Vite dev-server port.
EXPOSE 5173

# Command to run the application. --host 0.0.0.0 so the container is reachable.
CMD ["pnpm", "dev", "--host", "0.0.0.0"]
