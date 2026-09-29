FROM node:20-alpine AS build
WORKDIR /app

COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./
# Baked in at build time: Next inlines NEXT_PUBLIC_* into the client bundle.
ARG NEXT_PUBLIC_API_URL=http://localhost:8081
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build

FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production

COPY --from=build /app/public ./public
COPY --from=build /app/.next ./.next
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json

RUN addgroup -g 10001 tf && adduser -D -u 10001 -G tf tf && chown -R tf:tf /app
USER tf

EXPOSE 3000
CMD ["npm", "start"]
