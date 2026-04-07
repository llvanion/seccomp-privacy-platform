# Python Client (CLI + WebUI)

本目录是统一隐私平台客户端的 Python 实现（MVP）。

## 1. 安装依赖

```bash
pip install -r client/requirements.txt
```

## 2. CLI 使用

```bash
python -m client.interfaces.cli.main health
python -m client.interfaces.cli.main attribution-run --job-id demo_job --start-ts 1596439471 --end-ts 1596445871 --caller demo
python -m client.interfaces.cli.main se-search --index-name demo_index --keyword China
```

默认网关地址：`http://127.0.0.1:8000`

可通过参数覆盖：

```bash
python -m client.interfaces.cli.main --gateway-base-url http://127.0.0.1:9000 health
```

## 3. WebUI 启动

```bash
uvicorn client.interfaces.webui.main:app --host 127.0.0.1 --port 8080
```

打开：`http://127.0.0.1:8080`

## 4. 配置

配置由 `client/app/config.py` 统一读取，支持：
- 命令行参数覆盖
- 环境变量 `CLIENT_GATEWAY_BASE_URL`
