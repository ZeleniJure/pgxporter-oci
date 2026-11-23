FROM --platform=$BUILDPLATFORM golang:1.25-trixie AS build
WORKDIR /src

COPY go.mod go.sum* ./
RUN go mod download

COPY main.go ./

ARG TARGETOS
ARG TARGETARCH
ARG VERSION=dev
ARG GIT_SHA=unknown
RUN CGO_ENABLED=0 GOOS=${TARGETOS} GOARCH=${TARGETARCH} \
    go build -trimpath \
    -ldflags="-s -w -X main.version=${VERSION} -X main.gitSHA=${GIT_SHA}" \
    -o /out/pgxporter .

FROM gcr.io/distroless/static-debian13:nonroot
COPY --from=build /out/pgxporter /pgxporter
EXPOSE 9187
USER nonroot:nonroot
ENTRYPOINT ["/pgxporter"]
