FROM node:20-alpine AS build

WORKDIR /app

COPY package*.json /app/
RUN npm install

COPY . /app
RUN npm run build

FROM node:20-alpine

WORKDIR /app

COPY --from=build /app/package*.json /app/
COPY --from=build /app/node_modules /app/node_modules
COPY --from=build /app/dist /app/dist
COPY --from=build /app/vite.config.ts /app/vite.config.ts

EXPOSE 8080

CMD ["node", "/app/node_modules/vite/bin/vite.js", "preview", "--host", "0.0.0.0", "--port", "8080"]
