#!/usr/bin/env python3
import argparse
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_ID = "k8s_network_policy_report/v1"
_NAME_RE = re.compile(r"[^a-z0-9-]+")
_LABEL_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9_.-]{0,61}[A-Za-z0-9])?$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sanitize_name(value: str) -> str:
    cleaned = _NAME_RE.sub("-", value.lower()).strip("-")
    if not cleaned:
        cleaned = "tenant"
    if len(cleaned) > 45:
        cleaned = cleaned[:45].rstrip("-")
    return cleaned or "tenant"


def validate_label_value(value: str, *, field_name: str) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        raise ValueError(f"{field_name} must not be empty")
    if not _LABEL_RE.match(candidate):
        raise ValueError(
            f"{field_name}={candidate!r} is not a valid Kubernetes label value"
        )
    return candidate


def build_network_policy(
    *,
    tenant_id: str,
    namespace: str,
    recovery_app: str,
    pipeline_app: str,
    port: int,
    protocol: str,
) -> dict[str, Any]:
    tenant_label = validate_label_value(tenant_id, field_name="tenant_id")
    recovery_app = validate_label_value(recovery_app, field_name="recovery_app")
    pipeline_app = validate_label_value(pipeline_app, field_name="pipeline_app")
    name = f"recovery-service-ingress-{sanitize_name(tenant_label)}"
    metadata: dict[str, Any] = {
        "name": name,
        "labels": {
            "app": recovery_app,
            "tenant": tenant_label,
        },
    }
    if namespace:
        metadata["namespace"] = validate_label_value(namespace, field_name="namespace")
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": metadata,
        "spec": {
            "podSelector": {
                "matchLabels": {
                    "app": recovery_app,
                    "tenant": tenant_label,
                }
            },
            "policyTypes": ["Ingress"],
            "ingress": [
                {
                    "from": [
                        {
                            "podSelector": {
                                "matchLabels": {
                                    "app": pipeline_app,
                                    "tenant": tenant_label,
                                }
                            }
                        }
                    ],
                    "ports": [
                        {
                            "port": port,
                            "protocol": protocol,
                        }
                    ],
                }
            ],
        },
    }


def yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = str(value)
    if re.match(r"^[A-Za-z0-9_.:/-]+$", text):
        return text
    return json.dumps(text, ensure_ascii=False)


def to_yaml(value: Any, *, indent: int = 0) -> str:
    pad = " " * indent
    lines: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}{key}:")
                lines.append(to_yaml(item, indent=indent + 2))
            else:
                lines.append(f"{pad}{key}: {yaml_scalar(item)}")
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}-")
                lines.append(to_yaml(item, indent=indent + 2))
            else:
                lines.append(f"{pad}- {yaml_scalar(item)}")
    else:
        lines.append(f"{pad}{yaml_scalar(value)}")
    return "\n".join(lines)


def validate_network_policy(manifest: dict[str, Any], *, tenant_id: str, port: int, protocol: str) -> list[str]:
    errors: list[str] = []
    if manifest.get("apiVersion") != "networking.k8s.io/v1":
        errors.append("apiVersion must be networking.k8s.io/v1")
    if manifest.get("kind") != "NetworkPolicy":
        errors.append("kind must be NetworkPolicy")
    spec = manifest.get("spec") if isinstance(manifest.get("spec"), dict) else {}
    selector = ((spec.get("podSelector") or {}).get("matchLabels") or {}) if isinstance(spec, dict) else {}
    if selector.get("tenant") != tenant_id:
        errors.append("podSelector tenant label mismatch")
    ingress = spec.get("ingress") if isinstance(spec, dict) else None
    if not isinstance(ingress, list) or len(ingress) != 1:
        errors.append("exactly one ingress rule is required")
        return errors
    rule = ingress[0] if isinstance(ingress[0], dict) else {}
    sources = rule.get("from")
    if not isinstance(sources, list) or len(sources) != 1:
        errors.append("exactly one ingress source is required")
    else:
        source_labels = (((sources[0] or {}).get("podSelector") or {}).get("matchLabels") or {})
        if source_labels.get("tenant") != tenant_id:
            errors.append("pipeline source tenant label mismatch")
    ports = rule.get("ports")
    if not isinstance(ports, list) or len(ports) != 1:
        errors.append("exactly one ingress port is required")
    else:
        if int(ports[0].get("port") or 0) != port:
            errors.append("port mismatch")
        if str(ports[0].get("protocol") or "") != protocol:
            errors.append("protocol mismatch")
    return errors


def run_kubectl_dry_run(manifest_path: Path) -> dict[str, Any]:
    kubectl = shutil.which("kubectl")
    if not kubectl:
        return {"status": "skipped", "reason": "kubectl_not_found"}
    proc = subprocess.run(
        [kubectl, "apply", "--dry-run=client", "-f", str(manifest_path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return {
        "status": "ok" if proc.returncode == 0 else "fail",
        "exit_code": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Render tenant-scoped Kubernetes NetworkPolicy manifests.")
    ap.add_argument("--tenant-id", action="append", default=[], help="Tenant label value; repeat for multiple tenants")
    ap.add_argument("--namespace", default="", help="Optional namespace for generated manifests")
    ap.add_argument("--recovery-app", default="recovery-service")
    ap.add_argument("--pipeline-app", default="sse-bridge-pipeline")
    ap.add_argument("--port", type=int, default=18443)
    ap.add_argument("--protocol", default="TCP", choices=["TCP", "UDP", "SCTP"])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--output", default="", help="Optional report JSON output path")
    ap.add_argument("--kubectl-dry-run", action="store_true", help="Run kubectl apply --dry-run=client when kubectl is available")
    ap.add_argument("--assert-ok", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    tenants = [tenant.strip() for tenant in args.tenant_id if tenant.strip()]
    if not tenants:
        raise SystemExit("[ERROR] at least one --tenant-id is required")
    if args.port <= 0:
        raise SystemExit("[ERROR] --port must be positive")

    out_dir = Path(args.out_dir).resolve()
    manifests: list[dict[str, Any]] = []
    for tenant_id in tenants:
        try:
            manifest = build_network_policy(
                tenant_id=tenant_id,
                namespace=args.namespace,
                recovery_app=args.recovery_app,
                pipeline_app=args.pipeline_app,
                port=args.port,
                protocol=args.protocol,
            )
            errors = validate_network_policy(
                manifest,
                tenant_id=tenant_id,
                port=args.port,
                protocol=args.protocol,
            )
            manifest_path = out_dir / f"netpol-recovery-service-{sanitize_name(tenant_id)}.yaml"
            write_text(manifest_path, to_yaml(manifest) + "\n")
            kubectl = run_kubectl_dry_run(manifest_path) if args.kubectl_dry_run else {"status": "not_requested"}
            manifests.append(
                {
                    "tenant_id": tenant_id,
                    "path": str(manifest_path),
                    "metadata_name": str((manifest.get("metadata") or {}).get("name") or ""),
                    "namespace": args.namespace or None,
                    "port": args.port,
                    "protocol": args.protocol,
                    "valid": not errors and kubectl.get("status") not in {"fail"},
                    "errors": errors,
                    "kubectl_dry_run": kubectl,
                }
            )
        except Exception as exc:
            manifests.append(
                {
                    "tenant_id": tenant_id,
                    "path": None,
                    "metadata_name": None,
                    "namespace": args.namespace or None,
                    "port": args.port,
                    "protocol": args.protocol,
                    "valid": False,
                    "errors": [str(exc)],
                    "kubectl_dry_run": {"status": "not_run"},
                }
            )

    status = "ok" if all(item["valid"] for item in manifests) else "fail"
    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now(),
        "status": status,
        "out_dir": str(out_dir),
        "tenant_count": len(manifests),
        "recovery_app": args.recovery_app,
        "pipeline_app": args.pipeline_app,
        "manifests": manifests,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        write_text(Path(args.output), text + "\n")
    print(text)
    if args.assert_ok and status != "ok":
        return 1
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
