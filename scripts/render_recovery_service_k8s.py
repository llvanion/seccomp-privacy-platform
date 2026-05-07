#!/usr/bin/env python3
"""J1: render Kubernetes Deployment / Service / HorizontalPodAutoscaler manifests
for the record-recovery service.

This is a sidecar-only renderer: it never modifies the privacy pipeline contracts
or main-chain code. It emits structurally-validated YAML manifests under --out-dir
and a topology report (k8s_recovery_service_topology_report/v1) summarising the
generated artifacts. With --kubectl-dry-run, each manifest is also fed through
`kubectl apply --dry-run=client` when kubectl is available locally; default smoke
runs structural validation only so CI does not need a Kubernetes client config.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_ID = "k8s_recovery_service_topology_report/v1"
_LABEL_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9_.-]{0,61}[A-Za-z0-9])?$")
_NAME_RE = re.compile(r"[^a-z0-9-]+")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sanitize_name(value: str) -> str:
    cleaned = _NAME_RE.sub("-", value.lower()).strip("-")
    if not cleaned:
        cleaned = "recovery"
    if len(cleaned) > 45:
        cleaned = cleaned[:45].rstrip("-")
    return cleaned or "recovery"


def validate_label_value(value: str, *, field_name: str) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        raise ValueError(f"{field_name} must not be empty")
    if not _LABEL_RE.match(candidate):
        raise ValueError(
            f"{field_name}={candidate!r} is not a valid Kubernetes label value"
        )
    return candidate


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
        if not value:
            lines.append(f"{pad}{{}}")
            return "\n".join(lines)
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                if isinstance(item, dict) and not item:
                    lines.append(f"{pad}{key}: {{}}")
                elif isinstance(item, list) and not item:
                    lines.append(f"{pad}{key}: []")
                else:
                    lines.append(f"{pad}{key}:")
                    lines.append(to_yaml(item, indent=indent + 2))
            else:
                lines.append(f"{pad}{key}: {yaml_scalar(item)}")
    elif isinstance(value, list):
        if not value:
            lines.append(f"{pad}[]")
            return "\n".join(lines)
        for item in value:
            if isinstance(item, dict):
                first = True
                for key, sub in item.items():
                    prefix = "- " if first else "  "
                    first = False
                    if isinstance(sub, (dict, list)):
                        lines.append(f"{pad}{prefix}{key}:")
                        lines.append(to_yaml(sub, indent=indent + 4))
                    else:
                        lines.append(f"{pad}{prefix}{key}: {yaml_scalar(sub)}")
            elif isinstance(item, list):
                lines.append(f"{pad}-")
                lines.append(to_yaml(item, indent=indent + 2))
            else:
                lines.append(f"{pad}- {yaml_scalar(item)}")
    else:
        lines.append(f"{pad}{yaml_scalar(value)}")
    return "\n".join(lines)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not text.endswith("\n"):
        text = text + "\n"
    path.write_text(text, encoding="utf-8")


def base_metadata(name: str, *, namespace: str, app: str, tenant_id: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "name": name,
        "labels": {
            "app": app,
            "tenant": tenant_id,
        },
    }
    if namespace:
        metadata["namespace"] = namespace
    return metadata


def build_deployment(
    *,
    namespace: str,
    app: str,
    tenant_id: str,
    image: str,
    container_port: int,
    replicas: int,
    config_secret: str,
    tls_secret: str,
    auth_token_secret: str,
) -> dict[str, Any]:
    name = f"{app}-{sanitize_name(tenant_id)}"
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": base_metadata(name, namespace=namespace, app=app, tenant_id=tenant_id),
        "spec": {
            "replicas": replicas,
            "selector": {
                "matchLabels": {
                    "app": app,
                    "tenant": tenant_id,
                }
            },
            "template": {
                "metadata": {
                    "labels": {
                        "app": app,
                        "tenant": tenant_id,
                    }
                },
                "spec": {
                    "containers": [
                        {
                            "name": "recovery-service",
                            "image": image,
                            "imagePullPolicy": "IfNotPresent",
                            "args": [
                                "python3",
                                "scripts/run_record_recovery_service.py",
                                "serve",
                                "--config",
                                "/etc/seccomp/recovery-service-config.json",
                            ],
                            "ports": [
                                {
                                    "name": "https",
                                    "containerPort": container_port,
                                    "protocol": "TCP",
                                }
                            ],
                            "env": [
                                {
                                    "name": "SSE_RECORD_RECOVERY_TOKEN",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": auth_token_secret,
                                            "key": "token",
                                        }
                                    },
                                }
                            ],
                            "volumeMounts": [
                                {
                                    "name": "recovery-config",
                                    "mountPath": "/etc/seccomp",
                                    "readOnly": True,
                                },
                                {
                                    "name": "recovery-tls",
                                    "mountPath": "/etc/seccomp/mtls",
                                    "readOnly": True,
                                },
                            ],
                            "readinessProbe": {
                                "httpGet": {
                                    "path": "/healthz",
                                    "port": "https",
                                    "scheme": "HTTPS",
                                },
                                "initialDelaySeconds": 5,
                                "periodSeconds": 10,
                                "timeoutSeconds": 3,
                            },
                            "livenessProbe": {
                                "httpGet": {
                                    "path": "/healthz",
                                    "port": "https",
                                    "scheme": "HTTPS",
                                },
                                "initialDelaySeconds": 15,
                                "periodSeconds": 30,
                                "timeoutSeconds": 3,
                            },
                            "resources": {
                                "requests": {
                                    "cpu": "100m",
                                    "memory": "128Mi",
                                },
                                "limits": {
                                    "cpu": "500m",
                                    "memory": "512Mi",
                                },
                            },
                        }
                    ],
                    "volumes": [
                        {
                            "name": "recovery-config",
                            "secret": {
                                "secretName": config_secret,
                            },
                        },
                        {
                            "name": "recovery-tls",
                            "secret": {
                                "secretName": tls_secret,
                            },
                        },
                    ],
                },
            },
        },
    }


def build_service(
    *,
    namespace: str,
    app: str,
    tenant_id: str,
    service_port: int,
    container_port: int,
) -> dict[str, Any]:
    name = f"{app}-{sanitize_name(tenant_id)}"
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": base_metadata(name, namespace=namespace, app=app, tenant_id=tenant_id),
        "spec": {
            "type": "ClusterIP",
            "selector": {
                "app": app,
                "tenant": tenant_id,
            },
            "ports": [
                {
                    "name": "https",
                    "port": service_port,
                    "targetPort": "https",
                    "protocol": "TCP",
                }
            ],
        },
    }


def build_hpa(
    *,
    namespace: str,
    app: str,
    tenant_id: str,
    min_replicas: int,
    max_replicas: int,
    target_cpu: int,
) -> dict[str, Any]:
    name = f"{app}-{sanitize_name(tenant_id)}"
    return {
        "apiVersion": "autoscaling/v2",
        "kind": "HorizontalPodAutoscaler",
        "metadata": base_metadata(name, namespace=namespace, app=app, tenant_id=tenant_id),
        "spec": {
            "scaleTargetRef": {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "name": name,
            },
            "minReplicas": min_replicas,
            "maxReplicas": max_replicas,
            "metrics": [
                {
                    "type": "Resource",
                    "resource": {
                        "name": "cpu",
                        "target": {
                            "type": "Utilization",
                            "averageUtilization": target_cpu,
                        },
                    },
                }
            ],
        },
    }


def validate_deployment(manifest: dict[str, Any], *, app: str, tenant_id: str, container_port: int, replicas: int) -> list[str]:
    errors: list[str] = []
    if manifest.get("apiVersion") != "apps/v1":
        errors.append("apiVersion must be apps/v1")
    if manifest.get("kind") != "Deployment":
        errors.append("kind must be Deployment")
    spec = manifest.get("spec") if isinstance(manifest.get("spec"), dict) else {}
    if int(spec.get("replicas") or 0) != replicas:
        errors.append(f"spec.replicas mismatch (expected {replicas})")
    selector = ((spec.get("selector") or {}).get("matchLabels") or {})
    if selector.get("app") != app or selector.get("tenant") != tenant_id:
        errors.append("selector labels must include app and tenant")
    template = spec.get("template") if isinstance(spec.get("template"), dict) else {}
    template_labels = (template.get("metadata") or {}).get("labels") or {}
    if template_labels.get("app") != app or template_labels.get("tenant") != tenant_id:
        errors.append("pod template labels must include app and tenant")
    containers = (template.get("spec") or {}).get("containers")
    if not isinstance(containers, list) or len(containers) != 1:
        errors.append("exactly one container is required")
        return errors
    container = containers[0]
    ports = container.get("ports") if isinstance(container.get("ports"), list) else []
    if not ports or int(ports[0].get("containerPort") or 0) != container_port:
        errors.append("container port mismatch")
    if not container.get("readinessProbe"):
        errors.append("container.readinessProbe is required for load-balancer health checks")
    if not container.get("livenessProbe"):
        errors.append("container.livenessProbe is required for stuck-pod detection")
    resources = container.get("resources") if isinstance(container.get("resources"), dict) else {}
    if not resources.get("requests") or not resources.get("limits"):
        errors.append("container.resources.{requests,limits} are required for HPA scheduling")
    return errors


def validate_service(manifest: dict[str, Any], *, app: str, tenant_id: str, service_port: int) -> list[str]:
    errors: list[str] = []
    if manifest.get("apiVersion") != "v1":
        errors.append("apiVersion must be v1")
    if manifest.get("kind") != "Service":
        errors.append("kind must be Service")
    spec = manifest.get("spec") if isinstance(manifest.get("spec"), dict) else {}
    if spec.get("type") != "ClusterIP":
        errors.append("service type must be ClusterIP")
    selector = spec.get("selector") if isinstance(spec.get("selector"), dict) else {}
    if selector.get("app") != app or selector.get("tenant") != tenant_id:
        errors.append("service selector must include app and tenant")
    ports = spec.get("ports") if isinstance(spec.get("ports"), list) else []
    if not ports or int(ports[0].get("port") or 0) != service_port:
        errors.append("service port mismatch")
    return errors


def validate_hpa(manifest: dict[str, Any], *, app: str, tenant_id: str, min_replicas: int, max_replicas: int) -> list[str]:
    errors: list[str] = []
    if manifest.get("apiVersion") != "autoscaling/v2":
        errors.append("apiVersion must be autoscaling/v2")
    if manifest.get("kind") != "HorizontalPodAutoscaler":
        errors.append("kind must be HorizontalPodAutoscaler")
    spec = manifest.get("spec") if isinstance(manifest.get("spec"), dict) else {}
    if int(spec.get("minReplicas") or 0) != min_replicas:
        errors.append(f"hpa.minReplicas mismatch (expected {min_replicas})")
    if int(spec.get("maxReplicas") or 0) != max_replicas:
        errors.append(f"hpa.maxReplicas mismatch (expected {max_replicas})")
    target = spec.get("scaleTargetRef") if isinstance(spec.get("scaleTargetRef"), dict) else {}
    if target.get("kind") != "Deployment":
        errors.append("hpa.scaleTargetRef.kind must be Deployment")
    metrics = spec.get("metrics") if isinstance(spec.get("metrics"), list) else []
    if not metrics:
        errors.append("hpa.metrics must define at least one metric")
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


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Render Kubernetes Deployment/Service/HPA manifests for the record-recovery service.")
    ap.add_argument("--namespace", default="seccomp-privacy")
    ap.add_argument("--recovery-app", default="recovery-service")
    ap.add_argument("--tenant-id", default="demo-tenant")
    ap.add_argument("--image", default="ghcr.io/seccomp-privacy/recovery-service:0.1.0")
    ap.add_argument("--container-port", type=int, default=18443)
    ap.add_argument("--service-port", type=int, default=443)
    ap.add_argument("--replicas", type=int, default=2)
    ap.add_argument("--min-replicas", type=int, default=2)
    ap.add_argument("--max-replicas", type=int, default=6)
    ap.add_argument("--target-cpu-utilization", type=int, default=70)
    ap.add_argument("--config-secret", default="recovery-service-config")
    ap.add_argument("--tls-secret", default="recovery-service-tls")
    ap.add_argument("--auth-token-secret", default="recovery-service-auth-token")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--output", default="", help="Optional report JSON output path")
    ap.add_argument("--kubectl-dry-run", action="store_true", help="Run kubectl apply --dry-run=client when kubectl is available")
    ap.add_argument("--assert-ok", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.replicas < 1:
        raise SystemExit("[ERROR] --replicas must be >= 1")
    if args.min_replicas < 1 or args.max_replicas < args.min_replicas:
        raise SystemExit("[ERROR] --min-replicas / --max-replicas are invalid")
    if args.target_cpu_utilization <= 0 or args.target_cpu_utilization > 100:
        raise SystemExit("[ERROR] --target-cpu-utilization must be in (0,100]")
    if args.container_port <= 0 or args.service_port <= 0:
        raise SystemExit("[ERROR] --container-port / --service-port must be positive")

    namespace = validate_label_value(args.namespace, field_name="namespace") if args.namespace else ""
    app = validate_label_value(args.recovery_app, field_name="recovery_app")
    tenant_id = validate_label_value(args.tenant_id, field_name="tenant_id")

    out_dir = Path(args.out_dir).resolve()
    suffix = sanitize_name(tenant_id)

    deployment = build_deployment(
        namespace=namespace,
        app=app,
        tenant_id=tenant_id,
        image=args.image,
        container_port=args.container_port,
        replicas=args.replicas,
        config_secret=args.config_secret,
        tls_secret=args.tls_secret,
        auth_token_secret=args.auth_token_secret,
    )
    service = build_service(
        namespace=namespace,
        app=app,
        tenant_id=tenant_id,
        service_port=args.service_port,
        container_port=args.container_port,
    )
    hpa = build_hpa(
        namespace=namespace,
        app=app,
        tenant_id=tenant_id,
        min_replicas=args.min_replicas,
        max_replicas=args.max_replicas,
        target_cpu=args.target_cpu_utilization,
    )

    deployment_path = out_dir / f"{app}-deployment-{suffix}.yaml"
    service_path = out_dir / f"{app}-service-{suffix}.yaml"
    hpa_path = out_dir / f"{app}-hpa-{suffix}.yaml"
    write_text(deployment_path, to_yaml(deployment))
    write_text(service_path, to_yaml(service))
    write_text(hpa_path, to_yaml(hpa))

    deployment_errors = validate_deployment(
        deployment, app=app, tenant_id=tenant_id, container_port=args.container_port, replicas=args.replicas
    )
    service_errors = validate_service(
        service, app=app, tenant_id=tenant_id, service_port=args.service_port
    )
    hpa_errors = validate_hpa(
        hpa, app=app, tenant_id=tenant_id, min_replicas=args.min_replicas, max_replicas=args.max_replicas
    )

    deployment_dry = run_kubectl_dry_run(deployment_path) if args.kubectl_dry_run else {"status": "not_requested"}
    service_dry = run_kubectl_dry_run(service_path) if args.kubectl_dry_run else {"status": "not_requested"}
    hpa_dry = run_kubectl_dry_run(hpa_path) if args.kubectl_dry_run else {"status": "not_requested"}

    manifests: list[dict[str, Any]] = [
        {
            "kind": "Deployment",
            "path": str(deployment_path),
            "metadata_name": (deployment.get("metadata") or {}).get("name"),
            "valid": not deployment_errors and deployment_dry.get("status") not in {"fail"},
            "errors": deployment_errors,
            "kubectl_dry_run": deployment_dry,
        },
        {
            "kind": "Service",
            "path": str(service_path),
            "metadata_name": (service.get("metadata") or {}).get("name"),
            "valid": not service_errors and service_dry.get("status") not in {"fail"},
            "errors": service_errors,
            "kubectl_dry_run": service_dry,
        },
        {
            "kind": "HorizontalPodAutoscaler",
            "path": str(hpa_path),
            "metadata_name": (hpa.get("metadata") or {}).get("name"),
            "valid": not hpa_errors and hpa_dry.get("status") not in {"fail"},
            "errors": hpa_errors,
            "kubectl_dry_run": hpa_dry,
        },
    ]

    status = "ok" if all(item["valid"] for item in manifests) else "fail"
    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now(),
        "status": status,
        "out_dir": str(out_dir),
        "namespace": namespace or None,
        "recovery_app": app,
        "tenant_id": tenant_id,
        "service_port": args.service_port,
        "container_port": args.container_port,
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
