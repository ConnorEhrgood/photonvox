# The PhotonVox web app: the static bundle built with Node, served by unprivileged nginx (the PhotonID directory's pattern). Nothing Node-related
# ships in the final image. The context is this folder alone: the design system is vendored into src/ (photon-ui's scripts/sync-vendored.mjs).
FROM node:22.23.3-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Vite bakes these into the bundle at build time, not at run time. They are public values (they end up in the page).
ARG VITE_API_URL
ARG VITE_OIDC_ISSUER
ARG VITE_OIDC_CLIENT_ID
ARG VITE_OIDC_AUDIENCE_PROJECT
ARG VITE_DIRECTORY_APP_URL
ARG VITE_DIRECTORY_API_URL
ARG VITE_DIRECTORY_AUDIENCE_PROJECT
ENV VITE_API_URL=$VITE_API_URL VITE_OIDC_ISSUER=$VITE_OIDC_ISSUER VITE_OIDC_CLIENT_ID=$VITE_OIDC_CLIENT_ID \
    VITE_OIDC_AUDIENCE_PROJECT=$VITE_OIDC_AUDIENCE_PROJECT VITE_DIRECTORY_APP_URL=$VITE_DIRECTORY_APP_URL \
    VITE_DIRECTORY_API_URL=$VITE_DIRECTORY_API_URL VITE_DIRECTORY_AUDIENCE_PROJECT=$VITE_DIRECTORY_AUDIENCE_PROJECT
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.29.3-alpine
ARG VITE_API_URL
ARG VITE_OIDC_ISSUER
ARG VITE_DIRECTORY_API_URL=https://api.account.photonind.com
ARG BUILD_SHA=unknown
LABEL org.opencontainers.image.revision=$BUILD_SHA org.opencontainers.image.title="PhotonVox web"
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
# The Content-Security-Policy allows calls only to the API's own origin, PhotonID (sign-in) and the directory's API (the app switcher's list);
# all known only at build time.
USER root
RUN API_ORIGIN="$(echo "${VITE_API_URL:-http://localhost:8113}" | sed -E 's#^([a-z]+://[^/]+).*#\1#')" \
    && OIDC_ORIGIN="$(echo "${VITE_OIDC_ISSUER:-}" | sed -E 's#^([a-z]+://[^/]+).*#\1#')" \
    && DIRECTORY_ORIGIN="$(echo "${VITE_DIRECTORY_API_URL:-}" | sed -E 's#^([a-z]+://[^/]+).*#\1#')" \
    && sed -i "s#__API_ORIGIN__#${API_ORIGIN}#g; s#__OIDC_ORIGIN__#${OIDC_ORIGIN}#g; s#__DIRECTORY_ORIGIN__#${DIRECTORY_ORIGIN}#g" /etc/nginx/conf.d/default.conf
USER 101
EXPOSE 8080
