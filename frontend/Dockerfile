FROM node:22.23.0-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ARG VITE_GT_DEMO_TOKEN=dev-demo-token
ARG VITE_AUTH_MODE=demo
ARG VITE_OIDC_AUTHORITY=
ARG VITE_OIDC_CLIENT_ID=
ENV VITE_GT_DEMO_TOKEN=$VITE_GT_DEMO_TOKEN VITE_AUTH_MODE=$VITE_AUTH_MODE \
    VITE_OIDC_AUTHORITY=$VITE_OIDC_AUTHORITY VITE_OIDC_CLIENT_ID=$VITE_OIDC_CLIENT_ID
RUN npx tsc --noEmit -p tsconfig.json && npx vite build

FROM nginxinc/nginx-unprivileged:1.27.5-alpine
# rendered by the image's envsubst entrypoint at start; only GT_* variables are substituted
COPY frontend/nginx.conf.template /etc/nginx/templates/default.conf.template
ENV NGINX_ENVSUBST_FILTER=GT_ GT_CSP_CONNECT_EXTRA=""
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
