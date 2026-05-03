# -*- coding:utf-8 _*-
import os
from dataclasses import dataclass
from pathlib import Path

from services.record_recovery.bootstrap import ensure_repo_paths


ensure_repo_paths()

from services.record_recovery.authz import authz_policy_path, load_authz_policy  # noqa: E402


@dataclass
class RecordRecoveryServiceState:
    service_id: str
    tenant_id: str
    dataset_id: str
    auth_token: str
    metadata_db_path: str
    identity_token_config: str
    allowed_callers: set[str]
    authz_policy: dict
    authz_policy_path_value: str | None
    allowed_output_roots: list[Path]
    allowed_record_store_roots: list[Path]
    audit_log: Path | None
    transport: str = "unix_socket"
    socket_path: str | None = None
    endpoint_url: str | None = None
    max_rows_per_request: int = 0  # 0 = unlimited; positive value = hard cap per recovery request

    @property
    def server_address(self) -> str | None:
        if self.transport == "http":
            return self.endpoint_url
        return self.socket_path


def read_optional_env(env_name: str) -> str:
    if not env_name:
        return ""
    value = os.environ.get(env_name)
    if not value:
        raise ValueError(f"environment variable {env_name} is not set")
    return value


def parse_socket_mode(raw: str) -> int:
    try:
        return int(raw, 8)
    except ValueError as exc:
        raise ValueError(f"invalid socket mode {raw!r}; expected octal like 600") from exc


def write_text_file(path: Path | None, content: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_service_state(*,
                        service_id: str,
                        tenant_id: str,
                        dataset_id: str,
                        auth_token_env: str,
                        metadata_db_path: str,
                        identity_token_config: str,
                        allowed_callers: list[str],
                        authz_config: str,
                        allowed_output_roots: list[str],
                        allowed_record_store_roots: list[str],
                        audit_log: str,
                        transport: str,
                        socket_path: str | None,
                        endpoint_url: str | None,
                        max_rows_per_request: int = 0) -> RecordRecoveryServiceState:
    return RecordRecoveryServiceState(
        service_id=str(service_id or ""),
        tenant_id=str(tenant_id or ""),
        dataset_id=str(dataset_id or ""),
        auth_token=read_optional_env(auth_token_env),
        metadata_db_path=str(metadata_db_path or ""),
        identity_token_config=str(identity_token_config or ""),
        allowed_callers={str(item) for item in allowed_callers},
        authz_policy=load_authz_policy(authz_config),
        authz_policy_path_value=authz_policy_path(authz_config),
        allowed_output_roots=[Path(root) for root in allowed_output_roots],
        allowed_record_store_roots=[Path(root) for root in allowed_record_store_roots],
        audit_log=Path(audit_log) if audit_log else None,
        transport=transport,
        socket_path=socket_path,
        endpoint_url=endpoint_url,
        max_rows_per_request=max(0, int(max_rows_per_request or 0)),
    )
