FROM node:24-alpine AS dependencies
WORKDIR /app/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci

FROM node:24-alpine AS build
WORKDIR /app/apps/web
COPY --from=dependencies /app/apps/web/node_modules ./node_modules
COPY apps/web/package.json apps/web/package-lock.json apps/web/next.config.mjs apps/web/tsconfig.json ./
COPY apps/web/scripts/next.mjs ./scripts/next.mjs
COPY apps/web/src/app/*.tsx apps/web/src/app/*.css ./src/app/
COPY ["apps/web/src/app/[[][[]...path]]/page.tsx", "./src/app/[[...path]]/page.tsx"]
COPY apps/web/src/components/*.tsx apps/web/src/components/*.ts apps/web/src/components/*.css ./src/components/
COPY apps/web/src/lib/*.ts ./src/lib/
COPY apps/web/public/favicon.svg apps/web/public/robots.txt ./public/
COPY packages/i18n/index.ts /app/packages/i18n/index.ts
COPY packages/i18n/catalogs/*.json /app/packages/i18n/catalogs/
ARG CASEQUARRY_API_INTERNAL_URL=http://api:8000
ENV CASEQUARRY_API_INTERNAL_URL=$CASEQUARRY_API_INTERNAL_URL NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:24-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build --chown=node:node /app/apps/web/.next/standalone ./
COPY --from=build --chown=node:node /app/apps/web/.next/static ./apps/web/.next/static
COPY --from=build --chown=node:node /app/apps/web/public ./apps/web/public
USER node
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
