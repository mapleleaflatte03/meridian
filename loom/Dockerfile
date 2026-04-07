FROM rust:1.75-bookworm AS builder

WORKDIR /src

COPY Cargo.toml Cargo.lock ./
COPY crates ./crates
COPY README.md ./
COPY docs ./docs
COPY loom.toml.example ./

RUN cargo build --release --workspace --locked

FROM debian:bookworm-slim AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        python3 \
        procps \
        tini \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --home-dir /home/loom --shell /bin/bash loom \
    && mkdir -p /var/lib/loom \
    && chown -R loom:loom /var/lib/loom /home/loom

WORKDIR /var/lib/loom

COPY --from=builder /src/target/release/loom /usr/local/bin/loom

USER loom

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/loom"]
CMD ["help"]
