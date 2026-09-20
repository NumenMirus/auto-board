# syntax=docker/dockerfile:1.7
# AutoBreadboard frontend image (SvelteKit + adapter-static).
# Multi-stage: builder compiles the static bundle under adapter-static
# (svelte.config.js -> pages: "build", fallback: "index.html"); the runtime
# stage serves the bundle from nginxinc/nginx-unprivileged:alpine on :8080.
#
# `npm ci` is used for reproducibility against the committed
# package-lock.json. If the lockfile is ever removed or regenerated, switch
# back to `npm install` (the dev target also uses `npm install` because
# bind-mounted source has no pre-baked node_modules).

# ----- builder ---------------------------------------------------------------
FROM node:22-alpine AS builder

WORKDIR /app

# Copy lockfile + manifest first so `npm ci` can reuse a cached layer until
# either of them changes.
COPY package.json package-lock.json ./

# `npm ci` requires package-lock.json; pinned versions are honoured exactly.
RUN npm ci

# Now copy the rest of the source. node_modules is excluded by the .dockerignore
# (see project root) so the in-container node_modules is the one npm ci built.
COPY . .

# adapter-static writes the pre-rendered site + SPA fallback to `build/`.
RUN npm run build


# ----- dev (compose target) ---------------------------------------------------
FROM node:22-alpine AS dev

WORKDIR /app

COPY package.json package-lock.json ./

# Under Compose the source tree is bind-mounted at /app and the named volume
# `frontend_node_modules` overrides the in-bind node_modules (see
# infra/docker-compose.yml). That means `npm install` here only seeds the
# volume on first boot — Vite's HMR runs against the bind mount.
RUN npm install

COPY . .

EXPOSE 5173

# Vite dev server bound to all interfaces so docker port-forwarding works.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]


# ----- runtime ---------------------------------------------------------------
FROM nginxinc/nginx-unprivileged:alpine AS runtime

# Replace the stock unprivileged nginx config with ours. nginx-unprivileged
# already listens on 8080 by default, but we set it explicitly for clarity.
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Static bundle produced by the builder stage.
COPY --from=builder /app/build /usr/share/nginx/html

EXPOSE 8080

# nginx-unprivileged's default CMD already starts nginx in the foreground.