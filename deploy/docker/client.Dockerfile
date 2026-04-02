FROM ubuntu:24.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       bash \
       ca-certificates \
       coreutils \
       python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY moduleA_psi /app/moduleA_psi
COPY private-join-and-compute/bazel-bin/private_join_and_compute /app/private_join_and_compute

ENV PJC_BIN_DIR=/app
ENV PJC_BUILD=0
ENV OUT_DIR=/data/out
ENV CLIENT_CSV=/data/input/client.csv
ENV SERVER_ADDR=server.example.internal:10501
ENV GRPC_MAX_MESSAGE_MB=512
ENV SERVER_CONNECT_RETRIES=20
ENV SERVER_CONNECT_DELAY_SEC=2

VOLUME ["/data"]

CMD ["bash", "/app/moduleA_psi/scripts/run_pjc_client.sh"]
