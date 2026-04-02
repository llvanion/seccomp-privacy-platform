FROM ubuntu:24.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       bash \
       ca-certificates \
       coreutils \
       iproute2 \
       procps \
       python3 \
       tee \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY moduleA_psi /app/moduleA_psi
COPY private-join-and-compute/bazel-bin/private_join_and_compute /app/private_join_and_compute

ENV PJC_BIN_DIR=/app
ENV PJC_BUILD=0
ENV SERVER_ADDR=0.0.0.0:10501
ENV OUT_DIR=/data/out
ENV SERVER_CSV=/data/input/server.csv
ENV GRPC_MAX_MESSAGE_MB=512

VOLUME ["/data"]
EXPOSE 10501 18080

CMD ["bash", "/app/moduleA_psi/scripts/run_pjc_server.sh"]
