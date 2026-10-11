FROM node:22.23.0-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ARG VITE_GT_DEMO_TOKEN=dev-demo-token
ENV VITE_GT_DEMO_TOKEN=$VITE_GT_DEMO_TOKEN
RUN npx tsc --noEmit -p tsconfig.json && npx vite build

FROM nginxinc/nginx-unprivileged:1.27.5-alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
