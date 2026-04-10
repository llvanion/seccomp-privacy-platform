# Docker Runtime Notes

These images are runtime-only wrappers around the split PJC scripts:

- `moduleA_psi/scripts/run_pjc_server.sh`
- `moduleA_psi/scripts/run_pjc_client.sh`

They are meant for deployment with prebuilt PJC binaries. The Dockerfiles copy:

- `moduleA_psi/`
- `private-join-and-compute/bazel-bin/private_join_and_compute/`

This means the host that builds the image should first compile:

```bash
cd private-join-and-compute
bazel build -c opt //private_join_and_compute:server //private_join_and_compute:client
```

## Build

```bash
docker build -f deploy/docker/server.Dockerfile -t pjc-server:latest .
docker build -f deploy/docker/client.Dockerfile -t pjc-client:latest .
```

## Run server

```bash
docker run --rm \
  -p 10501:10501 \
  -v "$PWD/data/server:/data/input" \
  -v "$PWD/data/server-out:/data/out" \
  -e SERVER_CSV=/data/input/server.csv \
  -e SERVER_ADDR=0.0.0.0:10501 \
  pjc-server:latest
```

## Run client

```bash
docker run --rm \
  -v "$PWD/data/client:/data/input" \
  -v "$PWD/data/client-out:/data/out" \
  -e CLIENT_CSV=/data/input/client.csv \
  -e SERVER_ADDR=192.168.1.20:10501 \
  pjc-client:latest
```

## Result callback service

If the server side also needs the final result, run:

```bash
python3 moduleA_psi/scripts/result_sink_server.py --out-dir /path/to/results --port 18080
```

Then set the client-side callback variables:

```bash
export RESULT_CALLBACK_URL=http://server-host:18080/results
export RESULT_CALLBACK_TOKEN=optional-shared-token
```
