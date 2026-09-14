FROM ellejva20260914.azurecr.io/build/rust@sha256:4e543ec9da930f1d15301334d44bddfbeb824c4bb1c34a81dfd2115825f303a9 AS build
WORKDIR /src
COPY .cargo/ .cargo/
COPY rust/Cargo.toml rust/Cargo.lock rust/
COPY rust/src/ rust/src/
COPY app/wisdom/catalog.json app/wisdom/catalog.json
WORKDIR /src/rust
RUN cargo build --release --locked

FROM mcr.microsoft.com/azurelinux/base/core@sha256:c877612270d1ee2d6ab2bc1f64bfe38ab697ac50be325154ee5129fce89c17e4
COPY --from=build /src/rust/target/release/elle /usr/local/bin/elle
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/elle"]
CMD ["serve"]
