from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import importlib
import os
from pathlib import Path
import sys
import time
from typing import Any

from app.errors import GatewayError


@dataclass
class LocalIndex:
    values_by_key: dict[str, list[str]] = field(default_factory=dict)


class LocalFallbackBackend:
    def __init__(self) -> None:
        self._indices: dict[str, LocalIndex] = {}

    def build_index(self, index_name: str, records: list[dict[str, Any]]) -> int:
        idx = LocalIndex()
        for item in records:
            keys = item.get("keys", [])
            values = item.get("values", [])
            for key in keys:
                idx.values_by_key.setdefault(str(key), []).extend([str(v) for v in values])
        self._indices[index_name] = idx
        return sum(len(v) for v in idx.values_by_key.values())

    def search(self, index_name: str, keyword: str) -> tuple[list[str], float]:
        started = time.perf_counter()
        idx = self._indices.get(index_name, LocalIndex())
        results = idx.values_by_key.get(keyword, [])
        latency_ms = (time.perf_counter() - started) * 1000
        return results, latency_ms


class BPythonApiBackend:
    def __init__(self, *, sse_root: str, server_uri: str, scheme: str) -> None:
        if not sse_root:
            raise GatewayError("b_root_missing", "B_SSE_ROOT is required for python_api backend", status_code=500)

        self._sse_root = Path(sse_root).expanduser().resolve()
        if not self._sse_root.exists():
            raise GatewayError("b_root_not_found", f"B_SSE_ROOT not found: {self._sse_root}", status_code=500)

        if str(self._sse_root) not in sys.path:
            sys.path.insert(0, str(self._sse_root))

        global_config = importlib.import_module("global_config")
        global_config.ClientConfig.SERVER_URI = server_uri

        self._service_module = importlib.import_module("frontend.client.services.service")
        self._schemes_module = importlib.import_module("schemes")
        self._scheme = scheme
        self._index_sid: dict[str, str] = {}

    @contextmanager
    def _sse_cwd(self):
        prev = Path.cwd()
        os.chdir(self._sse_root)
        try:
            yield
        finally:
            os.chdir(prev)

    def build_index(self, index_name: str, records: list[dict[str, Any]]) -> int:
        import asyncio

        multi_key_db = []
        indexed_count = 0
        for item in records:
            keys = [str(k) for k in item.get("keys", [])]
            values = [str(v) for v in item.get("values", [])]
            if not keys or not values:
                continue
            multi_key_db.append({"keys": keys, "values": values})
            indexed_count += len(keys) * len(values)

        if not multi_key_db:
            return 0

        async def _run() -> str:
            with self._sse_cwd():
                service = self._service_module.Service()
                loader = self._schemes_module.load_sse_module(self._scheme)
                config = loader.SSEConfig.get_default_config()
                sid = service.handle_create_config(config, overwrite=True)
                service.handle_create_key(overwrite=True)
                service.handle_encrypt_database_multi_key(multi_key_db)
                await service.handle_upload_config(wait=True, overwrite=True)
                await service.handle_upload_encrypted_database(wait=True, overwrite=True)
                await service.close_service()
                return sid

        try:
            sid = asyncio.run(_run())
        except Exception as exc:
            raise GatewayError("b_build_failed", f"B index build failed: {exc}", status_code=502) from exc

        self._index_sid[index_name] = sid
        return indexed_count

    def search(self, index_name: str, keyword: str) -> tuple[list[str], float]:
        import asyncio

        sid = self._index_sid.get(index_name)
        if not sid:
            raise GatewayError("b_index_not_found", f"index not found: {index_name}", status_code=404)

        async def _run() -> list[str]:
            with self._sse_cwd():
                service = self._service_module.Service(sid)
                out: dict[str, list[str]] = {"results": []}

                def _capture(fut):
                    content = fut.result()
                    result_obj = service.sse_module_loader.SSEResult.deserialize(content, service.config_object)
                    out["results"] = [item.hex() for item in result_obj.get_result_list()]

                await service.handle_keyword_search(keyword.encode("utf-8"), wait=True, wait_callback_func=_capture)
                await service.close_service()
                return out["results"]

        started = time.perf_counter()
        try:
            results = asyncio.run(_run())
        except GatewayError:
            raise
        except Exception as exc:
            raise GatewayError("b_search_failed", f"B search failed: {exc}", status_code=502) from exc
        latency_ms = (time.perf_counter() - started) * 1000
        return results, latency_ms


class BAdapter:
    def __init__(
        self,
        *,
        backend: str,
        sse_root: str,
        server_uri: str,
        scheme: str,
    ) -> None:
        self._local = LocalFallbackBackend()
        self._backend_used = "local"
        self._remote: BPythonApiBackend | None = None

        if backend == "local":
            return

        try:
            self._remote = BPythonApiBackend(sse_root=sse_root, server_uri=server_uri, scheme=scheme)
            self._backend_used = "python_api"
        except Exception:
            if backend == "python_api":
                raise

    @property
    def backend_used(self) -> str:
        return self._backend_used

    def build_index(self, index_name: str, records: list[dict[str, Any]]) -> int:
        if self._remote is not None:
            return self._remote.build_index(index_name, records)
        return self._local.build_index(index_name, records)

    def search(self, index_name: str, keyword: str) -> tuple[list[str], float]:
        if self._remote is not None:
            return self._remote.search(index_name, keyword)
        return self._local.search(index_name, keyword)

