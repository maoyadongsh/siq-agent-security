FROM node:22-bookworm-slim AS build
WORKDIR /app
ARG SIQ_AS_WEB_BASE=/agent-security/
ARG VITE_API_BASE=/api/agent-security/v1
ARG VITE_IAM_URL=/api/iam
ARG VITE_DEV_MODE=false
ENV SIQ_AS_WEB_BASE=$SIQ_AS_WEB_BASE \
    VITE_API_BASE=$VITE_API_BASE \
    VITE_IAM_URL=$VITE_IAM_URL \
    VITE_DEV_MODE=$VITE_DEV_MODE
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.29.7-alpine3.23
RUN apk upgrade --no-cache
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
