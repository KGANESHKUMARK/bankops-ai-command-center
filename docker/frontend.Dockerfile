# BankOps AI Command Center — Frontend image
# Multi-stage: build the Vite production bundle, then serve with Nginx.
# SYNTHETIC DEMO ONLY.

FROM node:22-slim AS builder

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ---- runtime stage ----
FROM nginx:1.27-slim AS runtime

COPY --from=builder /build/dist /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
