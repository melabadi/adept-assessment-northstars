# syntax=docker/dockerfile:1
# RequestHub API + web UI. Built remotely in Azure Container Registry by `azd deploy` (no local Docker needed).

FROM node:22-alpine AS web
WORKDIR /src
COPY web/package.json web/package-lock.json web/
RUN cd web && npm ci --no-audit --no-fund
COPY web/ web/
RUN mkdir -p src/RequestHub.Api/wwwroot && cd web && npm run build

FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src
COPY Directory.Build.props Directory.Packages.props ./
COPY src/RequestHub.Core/RequestHub.Core.csproj src/RequestHub.Core/
COPY src/RequestHub.Api/RequestHub.Api.csproj src/RequestHub.Api/
RUN dotnet restore src/RequestHub.Api/RequestHub.Api.csproj
COPY src/ src/
COPY --from=web /src/src/RequestHub.Api/wwwroot/ src/RequestHub.Api/wwwroot/
RUN dotnet publish src/RequestHub.Api/RequestHub.Api.csproj -c Release -o /app --no-restore

FROM mcr.microsoft.com/dotnet/aspnet:10.0 AS final
WORKDIR /app
COPY --from=build /app .
ARG BUILD_SHA=local
ENV BUILD_SHA=${BUILD_SHA} \
    ASPNETCORE_HTTP_PORTS=8080 \
    OTEL_SERVICE_NAME=requesthub-api
EXPOSE 8080
USER $APP_UID
ENTRYPOINT ["dotnet", "RequestHub.Api.dll"]
