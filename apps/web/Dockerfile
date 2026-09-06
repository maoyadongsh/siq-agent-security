# Enterprise web UI image (DEV17-D): Node/nginx bases pinned by digest.
FROM node:22-bookworm-slim@sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5 AS build
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

FROM nginx:1.29.7-alpine3.23@sha256:e7257f1ef28ba17cf7c248cb8ccf6f0c6e0228ab9c315c152f9c203cd34cf6d1
RUN apk upgrade --no-cache
COPY security-headers.inc /etc/nginx/conf.d/security-headers.inc
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
