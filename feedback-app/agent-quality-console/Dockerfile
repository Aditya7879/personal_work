FROM node:24-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html vite.config.ts tsconfig.json ./
COPY src ./src
ARG VITE_AUTH_MODE=google_iam
ENV VITE_API_URL="" VITE_AUTH_MODE=${VITE_AUTH_MODE}
RUN npm run build

FROM node:24-bookworm-slim
ENV NODE_ENV=production PORT=8080
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY server.mjs ./
COPY --from=build /app/dist ./dist
USER node
CMD ["node", "server.mjs"]
