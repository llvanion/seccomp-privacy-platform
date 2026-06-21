import { useEffect, useState } from "react";
import { ApiError } from "@/api/client";
import { operatorApi } from "@/api/operator";
import type { Json } from "@/api/types";
import { Button, Card, CardHeader, EmptyState, ErrorBanner, Field, Input, JsonDetails, KeyValueGrid, PageHeader, StatTile, StatusPill, Textarea, inferStatusKind } from "@/components/ui";
import { useToast } from "@/components/toast";
import { useStoredState } from "@/hooks/useStoredState";
import { useApiMutation } from "@/hooks/useApi";
import { formatNumber, formatTimestamp, shortHash } from "@/lib/format";

const DEFAULT_SERVER_HOST = "100.101.31.53";
const DEFAULT_CLIENT_HOST = "100.99.96.96";
const DEFAULT_JOB_ID = "cross-vps-008";
const DEFAULT_CERT_DIR = "tmp/pjc_mtls_shared/certs";
const DEFAULT_ROLE_ROOT = "tmp/pjc_role_dirs";
const DEFAULT_PACKAGE_ROOT = "tmp/pjc_two_party/role_packages";
const DEFAULT_RUN_ROOT = "tmp/pjc_two_party/runs";
const DEFAULT_SIGNED_ROOT = "tmp/pjc_two_party/signed_manifests";
const DEFAULT_TWO_PARTY_ROOT = "tmp/pjc_two_party";
const DEFAULT_POLICY_CONFIG = "config/release_policy_gate.example.json";
const DEFAULT_PRIVACY_LEDGER = "tmp/defense_demo/privacy_budget/ledger.json";
const DEFAULT_HELPER_PATH = "a-psi/moduleA_psi/scripts/run_pjc_bucketed_tls_client.sh";
const DEFAULT_PJC_BIN_DIR = "a-psi/private-join-and-compute/bazel-bin";
const DEFAULT_SERVER_ROLE_DIR = "tmp/pjc_bucketed_scale_cross-vps-008_cleanrun/party_a_job";
const DEFAULT_CLIENT_ROLE_DIR = "tmp/pjc_bucketed_scale_cross-vps-008_cleanrun/party_b_job";
const DEFAULT_SERVER_RESULT_DIR = `${DEFAULT_RUN_ROOT}/cross-vps-008_server`;
const DEFAULT_CLIENT_RESULT_DIR = `${DEFAULT_RUN_ROOT}/cross-vps-008_client`;

type StepResult = Record<string, Json> | string | undefined;
type JsonRecord = Record<string, Json>;

export function PjcTwoPartyRoute() {
  const toast = useToast();

  const [jobId, setJobId] = useStoredState("console.pjc_two_party.job_id", DEFAULT_JOB_ID);
  const [serverHost, setServerHost] = useStoredState("console.pjc_two_party.server_host", DEFAULT_SERVER_HOST);
  const [clientHost, setClientHost] = useStoredState("console.pjc_two_party.client_host", DEFAULT_CLIENT_HOST);
  const [dashboardPort, setDashboardPort] = useStoredState("console.pjc_two_party.dashboard_port", "18134");
  const [dataplanePort, setDataplanePort] = useStoredState("console.pjc_two_party.dataplane_port", "10596");
  const [serverHostname, setServerHostname] = useStoredState("console.pjc_two_party.server_hostname", "pjc-server");
  const [expectedPeerIdentity, setExpectedPeerIdentity] = useStoredState("console.pjc_two_party.expected_peer_identity", "");
  const [repoCommit, setRepoCommit] = useStoredState("console.pjc_two_party.expected_commit", "");
  const [certDir, setCertDir] = useStoredState("console.pjc_two_party.cert_dir", DEFAULT_CERT_DIR);
  const [serverRoleDir, setServerRoleDir] = useStoredState("console.pjc_two_party.server_role_dir", DEFAULT_SERVER_ROLE_DIR);
  const [clientRoleDir, setClientRoleDir] = useStoredState("console.pjc_two_party.client_role_dir", DEFAULT_CLIENT_ROLE_DIR);
  const [packageRoot, setPackageRoot] = useStoredState("console.pjc_two_party.package_root", DEFAULT_PACKAGE_ROOT);
  const [serverOutDir, setServerOutDir] = useStoredState("console.pjc_two_party.server_out_dir", DEFAULT_SERVER_RESULT_DIR);
  const [clientOutDir, setClientOutDir] = useStoredState("console.pjc_two_party.client_out_dir", DEFAULT_CLIENT_RESULT_DIR);
  const [signedManifestRoot, setSignedManifestRoot] = useStoredState("console.pjc_two_party.signed_root", DEFAULT_SIGNED_ROOT);
  const [policyConfigPath, setPolicyConfigPath] = useStoredState("console.pjc_two_party.policy_config_path", DEFAULT_POLICY_CONFIG);
  const [privacyBudgetLedger, setPrivacyBudgetLedger] = useStoredState("console.pjc_two_party.privacy_budget_ledger", DEFAULT_PRIVACY_LEDGER);
  const [signingKeyPath, setSigningKeyPath] = useStoredState("console.pjc_two_party.signing_key_path", "");
  const [serverInputCsv, setServerInputCsv] = useStoredState("console.pjc_two_party.server_input_csv", "tmp/pjc_bucketed_scale_cross-vps-008_cleanrun/party_a_job/server.csv");
  const [clientInputCsv, setClientInputCsv] = useStoredState("console.pjc_two_party.client_input_csv", "tmp/pjc_bucketed_scale_cross-vps-008_cleanrun/party_b_job/client.csv");
  const [serverManifestPath, setServerManifestPath] = useStoredState("console.pjc_two_party.server_manifest_path", "tmp/pjc_bucketed_scale_cross-vps-008_cleanrun/party_a_job/input_commitments.json");
  const [clientManifestPath, setClientManifestPath] = useStoredState("console.pjc_two_party.client_manifest_path", "tmp/pjc_bucketed_scale_cross-vps-008_cleanrun/party_b_job/input_commitments.json");
  const [pjcBinDir, setPjcBinDir] = useStoredState("console.pjc_two_party.pjc_bin_dir", DEFAULT_PJC_BIN_DIR);
  const [helperScriptPath, setHelperScriptPath] = useStoredState("console.pjc_two_party.helper_script_path", DEFAULT_HELPER_PATH);
  const [productionMode, setProductionMode] = useStoredState("console.pjc_two_party.production_mode", false);
  const [requireSessionManifest, setRequireSessionManifest] = useStoredState("console.pjc_two_party.require_session_manifest", false);
  const [allowProductionWideBind, setAllowProductionWideBind] = useStoredState("console.pjc_two_party.allow_production_wide_bind", false);
  const [resourceLimitsPath, setResourceLimitsPath] = useStoredState("console.pjc_two_party.resource_limits_path", "config/pjc_resource_limits.example.json");
  const [allowLegacyUnary, setAllowLegacyUnary] = useStoredState("console.pjc_two_party.allow_legacy_unary", true);
  const [localProxyPortBase, setLocalProxyPortBase] = useStoredState("console.pjc_two_party.local_proxy_port_base", "11520");

  const [bootstrapUri, setBootstrapUri] = useStoredState("console.pjc_two_party.bootstrap_uri", "");
  const [caFingerprint, setCaFingerprint] = useStoredState("console.pjc_two_party.ca_fingerprint", "");
  const [serverPackagePath, setServerPackagePath] = useStoredState("console.pjc_two_party.server_package_path", "");
  const [clientPackagePath, setClientPackagePath] = useStoredState("console.pjc_two_party.client_package_path", "");
  const [partyADir, setPartyADir] = useStoredState("console.pjc_two_party.party_a_dir", serverOutDir);
  const [partyBDir, setPartyBDir] = useStoredState("console.pjc_two_party.party_b_dir", clientOutDir);
  const [serverResultPath, setServerResultPath] = useStoredState("console.pjc_two_party.server_result_path", `${serverOutDir}/attribution_result.json`);
  const [clientResultPath, setClientResultPath] = useStoredState("console.pjc_two_party.client_result_path", `${clientOutDir}/attribution_result.json`);
  const [serverPublicReportPath, setServerPublicReportPath] = useStoredState("console.pjc_two_party.server_public_report_path", `${serverOutDir}/public_report.json`);
  const [clientPublicReportPath, setClientPublicReportPath] = useStoredState("console.pjc_two_party.client_public_report_path", `${clientOutDir}/public_report.json`);
  const [serverAuditChainPath, setServerAuditChainPath] = useStoredState("console.pjc_two_party.server_audit_chain_path", `${serverOutDir}/audit_chain.json`);
  const [clientAuditChainPath, setClientAuditChainPath] = useStoredState("console.pjc_two_party.client_audit_chain_path", `${clientOutDir}/audit_chain.json`);
  const [inputCommitmentSha, setInputCommitmentSha] = useStoredState("console.pjc_two_party.input_commitment_sha", "");
  const [peerInputCommitmentSha, setPeerInputCommitmentSha] = useStoredState("console.pjc_two_party.peer_input_commitment_sha", "");
  const [bucketPolicySha, setBucketPolicySha] = useStoredState("console.pjc_two_party.bucket_policy_sha", "");
  const [peerBucketPolicySha, setPeerBucketPolicySha] = useStoredState("console.pjc_two_party.peer_bucket_policy_sha", "");
  const [tlsIdentity, setTlsIdentity] = useStoredState("console.pjc_two_party.tls_identity", "");
  const [peerTlsIdentity, setPeerTlsIdentity] = useStoredState("console.pjc_two_party.peer_tls_identity", "");
  const [policyAuditLogPath, setPolicyAuditLogPath] = useStoredState("console.pjc_two_party.policy_audit_log_path", `${serverOutDir}/policy_audit.jsonl`);
  const [operatorReportPath, setOperatorReportPath] = useStoredState("console.pjc_two_party.operator_report_path", `${serverOutDir}/operator_report.json`);

  const [inviteResult, setInviteResult] = useStoredState<StepResult>("console.pjc_two_party.invite_result", undefined);
  const [enrollResult, setEnrollResult] = useStoredState<StepResult>("console.pjc_two_party.enroll_result", undefined);
  const [serverPreflightResult, setServerPreflightResult] = useStoredState<StepResult>("console.pjc_two_party.server_preflight_result", undefined);
  const [clientPreflightResult, setClientPreflightResult] = useStoredState<StepResult>("console.pjc_two_party.client_preflight_result", undefined);
  const [serverPackageResult, setServerPackageResult] = useStoredState<StepResult>("console.pjc_two_party.server_package_result", undefined);
  const [clientPackageImportResult, setClientPackageImportResult] = useStoredState<StepResult>("console.pjc_two_party.client_package_import_result", undefined);
  const [clientPackageResult, setClientPackageResult] = useStoredState<StepResult>("console.pjc_two_party.client_package_result", undefined);
  const [serverPackageImportResult, setServerPackageImportResult] = useStoredState<StepResult>("console.pjc_two_party.server_package_import_result", undefined);
  const [serverStartResult, setServerStartResult] = useStoredState<StepResult>("console.pjc_two_party.server_start_result", undefined);
  const [clientStartResult, setClientStartResult] = useStoredState<StepResult>("console.pjc_two_party.client_start_result", undefined);
  const [serverStatusResult, setServerStatusResult] = useStoredState<StepResult>("console.pjc_two_party.server_status_result", undefined);
  const [clientStatusResult, setClientStatusResult] = useStoredState<StepResult>("console.pjc_two_party.client_status_result", undefined);
  const [serverCancelResult, setServerCancelResult] = useStoredState<StepResult>("console.pjc_two_party.server_cancel_result", undefined);
  const [clientCancelResult, setClientCancelResult] = useStoredState<StepResult>("console.pjc_two_party.client_cancel_result", undefined);
  const [serverManifestSignResult, setServerManifestSignResult] = useStoredState<StepResult>("console.pjc_two_party.server_manifest_sign_result", undefined);
  const [clientManifestSignResult, setClientManifestSignResult] = useStoredState<StepResult>("console.pjc_two_party.client_manifest_sign_result", undefined);
  const [evidenceMergeResult, setEvidenceMergeResult] = useStoredState<StepResult>("console.pjc_two_party.evidence_merge_result", undefined);
  const [releaseGateResult, setReleaseGateResult] = useStoredState<StepResult>("console.pjc_two_party.release_gate_result", undefined);
  const [tlsDiagnosticResult, setTlsDiagnosticResult] = useStoredState<StepResult>("console.pjc_two_party.tls_diagnostic_result", undefined);
  const [negativeCasesResult, setNegativeCasesResult] = useStoredState<StepResult>("console.pjc_two_party.negative_cases_result", undefined);
  const [publicResultSummary, setPublicResultSummary] = useState<JsonRecord | undefined>(undefined);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const currentPort = window.location.port.trim();
    if (!currentPort) return;
    if (dashboardPort === "18134" && currentPort !== "18134") {
      setDashboardPort(currentPort);
    }
  }, [dashboardPort, setDashboardPort]);

  const prepareInvite = useApiMutation(async () => {
    const data = await operatorApi.mtlsPartyAPrepare({
      server_host: serverHost,
      dashboard_port: numOr(dashboardPort, 18134),
      force_regenerate: false,
    });
    if (typeof data.bootstrap_uri === "string" && data.bootstrap_uri) {
      setBootstrapUri(data.bootstrap_uri);
    }
    if (typeof data.fingerprint === "string" && data.fingerprint) {
      setCaFingerprint(data.fingerprint);
    }
    setInviteResult(data);
    return data;
  }, {
    successToast: "Party A invite 已生成",
  });

  const enrollPartyB = useApiMutation(async () => {
    const data = await operatorApi.mtlsPartyBEnroll({
      bootstrap_uri: bootstrapUri,
      cert_dir: certDir,
      expected_ca_fingerprint: caFingerprint || undefined,
    });
    setEnrollResult(data);
    if (typeof data.fingerprint === "string" && data.fingerprint) {
      setCaFingerprint(data.fingerprint);
    }
    return data;
  }, {
    successToast: "Party B enroll 完成",
  });

  const serverPreflight = useApiMutation(async () => {
    const data = await operatorApi.mtlsPreflight(buildPreflightPayload({
      jobId,
      role: "server",
      peerHost: clientHost,
      peerPort: numOr(dataplanePort, 10502),
      certDir,
      serverHostname,
      expectedPeerIdentity,
      expectedCaFingerprint: caFingerprint,
      expectedCommit: repoCommit,
      helperScriptPath,
      pjcBinDir,
      inputCsvPath: serverInputCsv,
      inputManifestPath: serverManifestPath,
      outputDir: serverOutDir,
    }));
    setServerPreflightResult(data);
    return data;
  }, { successToast: "Server preflight 已执行", errorToast: false, onError: (err) => handleTypedError(err, setServerPreflightResult, toast, "Server preflight") });

  const clientPreflight = useApiMutation(async () => {
    const data = await operatorApi.mtlsPreflight(buildPreflightPayload({
      jobId,
      role: "client",
      peerHost: serverHost,
      peerPort: numOr(dataplanePort, 10502),
      certDir,
      serverHostname,
      expectedPeerIdentity,
      expectedCaFingerprint: caFingerprint,
      expectedCommit: repoCommit,
      helperScriptPath,
      pjcBinDir,
      inputCsvPath: clientInputCsv,
      inputManifestPath: clientManifestPath,
      outputDir: clientOutDir,
    }));
    setClientPreflightResult(data);
    return data;
  }, { successToast: "Client preflight 已执行", errorToast: false, onError: (err) => handleTypedError(err, setClientPreflightResult, toast, "Client preflight") });

  const exportServerPackage = useApiMutation(async () => {
    const data = await operatorApi.pjcRolePackageExport({
      job_id: jobId,
      role: "server",
      source_dir: serverRoleDir,
      output_dir: packageRoot,
      expected_host: serverHost,
      expected_peer_identity: expectedPeerIdentity || undefined,
      expected_ca_fingerprint_sha256: caFingerprint || undefined,
      dataplane_port: numOr(dataplanePort, 10502),
      operator_notes: `Party A package for ${jobId}`,
    });
    if (typeof data.package_path === "string") setServerPackagePath(data.package_path);
    setServerPackageResult(data);
    return data;
  }, { successToast: "Server role package 已导出" });

  const importServerPackageOnClient = useApiMutation(async () => {
    const data = await operatorApi.pjcRolePackageImport({
      package_path: serverPackagePath,
      target_dir: `${clientRoleDir}/peer_server_package`,
    });
    setClientPackageImportResult(data);
    return data;
  }, { successToast: "Client 端已导入 Party A package", errorToast: false, onError: (err) => handleTypedError(err, setClientPackageImportResult, toast, "Client import Party A package") });

  const exportClientPackage = useApiMutation(async () => {
    const data = await operatorApi.pjcRolePackageExport({
      job_id: jobId,
      role: "client",
      source_dir: clientRoleDir,
      output_dir: packageRoot,
      expected_host: clientHost,
      expected_peer_identity: expectedPeerIdentity || undefined,
      expected_ca_fingerprint_sha256: caFingerprint || undefined,
      dataplane_port: numOr(dataplanePort, 10502),
      operator_notes: `Party B package for ${jobId}`,
    });
    if (typeof data.package_path === "string") setClientPackagePath(data.package_path);
    setClientPackageResult(data);
    return data;
  }, { successToast: "Client role package 已导出" });

  const importClientPackageOnServer = useApiMutation(async () => {
    const data = await operatorApi.pjcRolePackageImport({
      package_path: clientPackagePath,
      target_dir: `${serverRoleDir}/peer_client_package`,
    });
    setServerPackageImportResult(data);
    return data;
  }, { successToast: "Server 端已导入 Party B package", errorToast: false, onError: (err) => handleTypedError(err, setServerPackageImportResult, toast, "Server import Party B package") });

  const startServer = useApiMutation(async () => {
      const data = await operatorApi.pjcRoleStart("server", {
        job_id: jobId,
        cert_dir: certDir,
        role_dir: serverRoleDir,
        out_dir: serverOutDir,
        tls_port: numOr(dataplanePort, 10502),
        pjc_local_port: 10501,
        bind_addr: productionMode ? "0.0.0.0" : serverHost,
        pjc_bin_dir: pjcBinDir,
        production_mode: productionMode,
        require_session_manifest: requireSessionManifest,
        allow_production_wide_bind: allowProductionWideBind,
        pjc_resource_limits: productionMode ? resourceLimitsPath : undefined,
        allow_legacy_unary: allowLegacyUnary,
        pjc_grpc_stream_chunk_elements: allowLegacyUnary ? 0 : 4096,
        server_csv: serverInputCsv,
      });
    setServerStartResult(data);
    return data;
  }, { successToast: "Party A server 已启动", errorToast: false, onError: (err) => handleTypedError(err, setServerStartResult, toast, "Start server role") });

  const startClient = useApiMutation(async () => {
      const data = await operatorApi.pjcRoleStart("client", {
        job_id: jobId,
        server_host: serverHost,
        cert_dir: certDir,
        role_dir: clientRoleDir,
        out_dir: clientOutDir,
        tls_port: numOr(dataplanePort, 10502),
        local_proxy_port: numOr(localProxyPortBase, 11503),
        pjc_bin_dir: pjcBinDir,
        production_mode: productionMode,
        require_session_manifest: requireSessionManifest,
        pjc_resource_limits: productionMode ? resourceLimitsPath : undefined,
        allow_legacy_unary: allowLegacyUnary,
        pjc_grpc_stream_chunk_elements: allowLegacyUnary ? 0 : 4096,
        client_csv: clientInputCsv,
      });
    setClientStartResult(data);
    return data;
  }, { successToast: "Party B client 已启动", errorToast: false, onError: (err) => handleTypedError(err, setClientStartResult, toast, "Start client role") });

  const refreshServerStatus = useApiMutation(async () => {
    const data = await operatorApi.pjcRoleStatus("server", jobId);
    setServerStatusResult(data);
    return data;
  }, { successToast: "Server status 已刷新" });

  const refreshClientStatus = useApiMutation(async () => {
    const data = await operatorApi.pjcRoleStatus("client", jobId);
    setClientStatusResult(data);
    return data;
  }, { successToast: "Client status 已刷新" });

  const cancelServer = useApiMutation(async () => {
    const data = await operatorApi.pjcRoleCancel("server", { job_id: jobId, reason: "operator_cancel_from_console" });
    setServerCancelResult(data);
    return data;
  }, { successToast: "Server role 已取消", errorToast: false, onError: (err) => handleTypedError(err, setServerCancelResult, toast, "Cancel server role") });

  const cancelClient = useApiMutation(async () => {
    const data = await operatorApi.pjcRoleCancel("client", { job_id: jobId, reason: "operator_cancel_from_console" });
    setClientCancelResult(data);
    return data;
  }, { successToast: "Client role 已取消", errorToast: false, onError: (err) => handleTypedError(err, setClientCancelResult, toast, "Cancel client role") });

  const signServerManifest = useApiMutation(async () => {
    const data = await operatorApi.pjcRunManifestSign({
      job_id: jobId,
      party: "party_a",
      peer_party: "party_b",
      signing_key_path: signingKeyPath,
      input_commitment_sha256: inputCommitmentSha,
      peer_input_commitment_sha256: peerInputCommitmentSha,
      bucket_policy_sha256: bucketPolicySha || undefined,
      peer_bucket_policy_sha256: peerBucketPolicySha || undefined,
      pjc_result_path: serverResultPath,
      public_report_path: serverPublicReportPath,
      audit_chain_path: serverAuditChainPath,
      tls_identity: tlsIdentity || undefined,
      peer_tls_identity: peerTlsIdentity || undefined,
      ca_fingerprint_sha256: caFingerprint || undefined,
      repo_commit: repoCommit || undefined,
      output_dir: signedManifestRoot,
    });
    setServerManifestSignResult(data);
    return data;
  }, { successToast: "Party A signed manifest 已写出" });

  const signClientManifest = useApiMutation(async () => {
    const data = await operatorApi.pjcRunManifestSign({
      job_id: jobId,
      party: "party_b",
      peer_party: "party_a",
      signing_key_path: signingKeyPath,
      input_commitment_sha256: peerInputCommitmentSha,
      peer_input_commitment_sha256: inputCommitmentSha,
      bucket_policy_sha256: peerBucketPolicySha || undefined,
      peer_bucket_policy_sha256: bucketPolicySha || undefined,
      pjc_result_path: clientResultPath,
      public_report_path: clientPublicReportPath,
      audit_chain_path: clientAuditChainPath,
      tls_identity: peerTlsIdentity || undefined,
      peer_tls_identity: tlsIdentity || undefined,
      ca_fingerprint_sha256: caFingerprint || undefined,
      repo_commit: repoCommit || undefined,
      output_dir: signedManifestRoot,
    });
    setClientManifestSignResult(data);
    return data;
  }, { successToast: "Party B signed manifest 已写出" });

  const verifyMerge = useApiMutation(async () => {
    const data = await operatorApi.pjcEvidenceVerifyMerge({
      job_id: jobId,
      party_a_dir: partyADir,
      party_b_dir: partyBDir,
      require_signed_manifests: true,
    });
    setEvidenceMergeResult(data);
    return data;
  }, { successToast: "Evidence merge 已执行", errorToast: false, onError: (err) => handleTypedError(err, setEvidenceMergeResult, toast, "Evidence verify-merge") });

  const runReleaseGate = useApiMutation(async () => {
    const mergePath = extractPath(evidenceMergeResult, "evidence_path");
    const data = await operatorApi.releasePolicyGate({
      public_report_path: serverPublicReportPath,
      policy_config_path: policyConfigPath,
      operator_report_path: operatorReportPath || undefined,
      privacy_budget_ledger: privacyBudgetLedger || undefined,
      pjc_evidence_merge_path: mergePath || undefined,
      policy_audit_log_path: policyAuditLogPath || undefined,
    });
    setReleaseGateResult(data);
    return data;
  }, { successToast: "Release gate 已执行", errorToast: false, onError: (err) => handleTypedError(err, setReleaseGateResult, toast, "Release policy gate") });

  const runTlsDiagnostic = useApiMutation(async () => {
    const data = await operatorApi.mtlsTlsDiagnostic({
      job_id: jobId,
      role: "client",
      peer_host: serverHost,
      peer_port: numOr(dataplanePort, 10502),
      cert_dir: certDir,
      server_hostname: serverHostname,
      server_log_path: extractLogPath(serverStatusResult) || extractLogPath(serverStartResult) || undefined,
    });
    setTlsDiagnosticResult(data);
    return data;
  }, { successToast: "TLS diagnostic 已完成" });

  const runNegativeCases = useApiMutation(async () => {
    const data = await operatorApi.mtlsNegativeCases({
      job_id: jobId,
      required_cases: [
        "wrong_token",
        "expired_token",
        "wrong_ca",
        "wrong_peer",
        "closed_port",
        "commit_mismatch",
        "modified_csv",
        "privacy_denial",
      ],
      scenarios: {
        wrong_ca: { job_id: jobId, expected_ca_fingerprint_sha256: "00:11:22:33" },
        wrong_peer: { job_id: jobId, expected_peer_identity: "spiffe://wrong-peer" },
        closed_port: { job_id: jobId, peer_host: serverHost, peer_port: 1 },
        commit_mismatch: { job_id: jobId, expected_commit: repoCommit || "deadbeef" },
        modified_csv: { job_id: jobId, input_csv_path: serverInputCsv, expected_input_csv_sha256: "deadbeef" },
        privacy_denial: { job_id: jobId },
      },
    });
    setNegativeCasesResult(data);
    return data;
  }, { successToast: "Negative cases 已执行", errorToast: false, onError: (err) => handleTypedError(err, setNegativeCasesResult, toast, "Negative cases") });

  const refreshPublicResults = useApiMutation(async () => {
    const data = await operatorApi.pjcTwoPartyResultSummary({
      job_id: jobId,
      party_a_dir: partyADir || undefined,
      party_b_dir: partyBDir || undefined,
      party_a_role_dir: serverRoleDir || undefined,
      party_b_role_dir: clientRoleDir || undefined,
      party_a_result_path: serverResultPath || undefined,
      party_b_result_path: clientResultPath || undefined,
      party_a_public_report_path: serverPublicReportPath || undefined,
      party_b_public_report_path: clientPublicReportPath || undefined,
      party_a_audit_chain_path: serverAuditChainPath || undefined,
      party_b_audit_chain_path: clientAuditChainPath || undefined,
      party_a_manifest_path: extractPath(serverManifestSignResult, "manifest_path") || undefined,
      party_b_manifest_path: extractPath(clientManifestSignResult, "manifest_path") || undefined,
      signed_manifest_root: signedManifestRoot || undefined,
      evidence_merge_path: extractPath(evidenceMergeResult, "evidence_path") || undefined,
      release_gate_path: extractPath(releaseGateResult, "evidence_path") || undefined,
    });
    setPublicResultSummary(data);
    return data;
  }, { successToast: "结果汇总已刷新", errorToast: false, onError: (err) => toast.pushError("结果汇总失败", err.message) });

  const releaseDecision = extractDecision(releaseGateResult);
  const mergeDecision = extractReportDecision(evidenceMergeResult);
  const serverRoleState = extractState(serverStatusResult) || extractNestedState(serverStartResult);
  const clientRoleState = extractState(clientStatusResult) || extractNestedState(clientStartResult);

  return (
    <div className="space-y-5">
      <PageHeader
        title="公网双机 PJC"
        description="在真实鉴权会话下完成 Party A / Party B 的 mTLS bootstrap、preflight、角色启动、状态查看、证据合并与 release gate。当前建议使用远端面板负责 Party A（VPS 100.101.31.53），本地面板负责 Party B（笔记本 100.99.96.96）。"
      />

      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <StatTile label="job_id" value={jobId || "—"} hint="shared across all steps" kind="info" />
        <StatTile label="Party A" value={serverHost} hint={`dashboard:${dashboardPort} / tls:${dataplanePort}`} kind="info" />
        <StatTile label="Party B" value={clientHost} hint={certDir} kind="info" />
        <StatTile label="merge / gate" value={<StatusPill kind={inferStatusKind(releaseDecision ?? mergeDecision)}>{releaseDecision ?? mergeDecision ?? "pending"}</StatusPill>} hint="evidence + release" kind={inferStatusKind(releaseDecision ?? mergeDecision)} />
      </section>

      <Card>
        <CardHeader title="共享上下文" description="统一维护双机运行所需的 job_id、远端 Party A 地址、本地 Party B 地址、证书目录、role/out 目录和 release gate 依赖；下面 6 步会直接复用这些值。" />
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-3">
          <Field label="job_id">
            <Input value={jobId} onChange={(e) => setJobId(e.target.value)} />
          </Field>
          <Field label="Party A server_host">
            <Input value={serverHost} onChange={(e) => setServerHost(e.target.value)} />
          </Field>
          <Field label="Party B host">
            <Input value={clientHost} onChange={(e) => setClientHost(e.target.value)} />
          </Field>
          <Field label="dashboard port">
            <Input value={dashboardPort} onChange={(e) => setDashboardPort(e.target.value)} />
          </Field>
          <Field label="dataplane port">
            <Input value={dataplanePort} onChange={(e) => setDataplanePort(e.target.value)} />
          </Field>
          <Field label="server_hostname">
            <Input value={serverHostname} onChange={(e) => setServerHostname(e.target.value)} />
          </Field>
          <Field label="cert_dir">
            <Input value={certDir} onChange={(e) => setCertDir(e.target.value)} />
          </Field>
          <Field label="expected peer identity">
            <Input value={expectedPeerIdentity} onChange={(e) => setExpectedPeerIdentity(e.target.value)} placeholder="可留空，按证据路径补齐" />
          </Field>
          <Field label="expected repo commit">
            <Input value={repoCommit} onChange={(e) => setRepoCommit(e.target.value)} placeholder="留空则不做 commit match gate" />
          </Field>
          <Field label="Party A role_dir">
            <Input value={serverRoleDir} onChange={(e) => setServerRoleDir(e.target.value)} />
          </Field>
          <Field label="Party B role_dir">
            <Input value={clientRoleDir} onChange={(e) => setClientRoleDir(e.target.value)} />
          </Field>
          <Field label="role package root">
            <Input value={packageRoot} onChange={(e) => setPackageRoot(e.target.value)} />
          </Field>
          <Field label="Party A out_dir">
            <Input value={serverOutDir} onChange={(e) => setServerOutDir(e.target.value)} />
          </Field>
          <Field label="Party B out_dir">
            <Input value={clientOutDir} onChange={(e) => setClientOutDir(e.target.value)} />
          </Field>
          <Field label="signed manifest root">
            <Input value={signedManifestRoot} onChange={(e) => setSignedManifestRoot(e.target.value)} />
          </Field>
          <Field label="release policy config">
            <Input value={policyConfigPath} onChange={(e) => setPolicyConfigPath(e.target.value)} />
          </Field>
        </div>
      </Card>

      <StepCard
        step="1"
        title="远端 Party A prepare invite"
        description="在远端 Party A 面板生成 bootstrap URI、pairing token 和 CA fingerprint，供本地 Party B 在真实鉴权会话里执行 enroll。默认 server_host 为 VPS 对外可达地址。"
        action={<Button variant="primary" onClick={() => prepareInvite.mutate(undefined as never)} loading={prepareInvite.isPending}>生成 invite</Button>}
        result={inviteResult}
      >
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
          <Field label="bootstrap_uri">
            <Textarea value={bootstrapUri} onChange={(e) => setBootstrapUri(e.target.value)} className="min-h-[120px]" spellCheck={false} />
          </Field>
          <Field label="CA fingerprint">
            <Textarea value={caFingerprint} onChange={(e) => setCaFingerprint(e.target.value)} className="min-h-[120px]" spellCheck={false} />
          </Field>
          <Field label="说明">
            <Textarea
              readOnly
              value={`prepare 会调用 POST /v1/pjc-mtls/party-a/prepare。\n当前 Party A enrollment URL = http://${serverHost}:${dashboardPort}/v1/pjc-mtls/enroll\n建议远端 Party A 页面的 dashboard port 与当前面板端口保持一致，避免 bootstrap_uri 指向旧入口。`}
              className="min-h-[120px]"
            />
          </Field>
        </div>
      </StepCard>

      <StepCard
        step="2"
        title="本地 Party B enroll"
        description="把远端 Party A 生成的 bootstrap URI 粘到本地面板后，Party B 会在本机生成 client.key，只提交 CSR；完成后证书落到 cert_dir，供后续 mTLS 与角色启动复用。"
        action={<Button variant="primary" onClick={() => enrollPartyB.mutate(undefined as never)} loading={enrollPartyB.isPending}>执行 enroll</Button>}
        result={enrollResult}
      >
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <Field label="bootstrap_uri">
            <Textarea value={bootstrapUri} onChange={(e) => setBootstrapUri(e.target.value)} className="min-h-[96px]" spellCheck={false} />
          </Field>
          <Field label="cert_dir">
            <Input value={certDir} onChange={(e) => setCertDir(e.target.value)} />
          </Field>
        </div>
      </StepCard>

      <StepCard
        step="3"
        title="双边 preflight"
        description="分别检查远端 Party A 与本地 Party B 的 commit、helper script、PJC binary、TCP/TLS、peer identity、input manifest 和 output dir。preflight deny 时也会展示 typed report，便于定位公网双机问题。"
        action={
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" onClick={() => serverPreflight.mutate(undefined as never)} loading={serverPreflight.isPending}>跑 Party A preflight</Button>
            <Button variant="secondary" onClick={() => clientPreflight.mutate(undefined as never)} loading={clientPreflight.isPending}>跑 Party B preflight</Button>
          </div>
        }
        result={undefined}
      >
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Card>
            <CardHeader title="Party A 输入" />
            <div className="space-y-3">
              <Field label="input_csv_path">
                <Input value={serverInputCsv} onChange={(e) => setServerInputCsv(e.target.value)} />
              </Field>
              <Field label="input_manifest_path">
                <Input value={serverManifestPath} onChange={(e) => setServerManifestPath(e.target.value)} />
              </Field>
              <Field label="output_dir">
                <Input value={serverOutDir} onChange={(e) => setServerOutDir(e.target.value)} />
              </Field>
            </div>
            <ResultSummary data={serverPreflightResult} />
          </Card>
          <Card>
            <CardHeader title="Party B 输入" />
            <div className="space-y-3">
              <Field label="input_csv_path">
                <Input value={clientInputCsv} onChange={(e) => setClientInputCsv(e.target.value)} />
              </Field>
              <Field label="input_manifest_path">
                <Input value={clientManifestPath} onChange={(e) => setClientManifestPath(e.target.value)} />
              </Field>
              <Field label="output_dir">
                <Input value={clientOutDir} onChange={(e) => setClientOutDir(e.target.value)} />
              </Field>
            </div>
            <ResultSummary data={clientPreflightResult} />
          </Card>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mt-3">
          <Field label="helper_script_path">
            <Input value={helperScriptPath} onChange={(e) => setHelperScriptPath(e.target.value)} />
          </Field>
          <Field label="pjc_bin_dir">
            <Input value={pjcBinDir} onChange={(e) => setPjcBinDir(e.target.value)} />
          </Field>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-3 mt-3">
          <Field label="resource_limits path">
            <Input value={resourceLimitsPath} onChange={(e) => setResourceLimitsPath(e.target.value)} />
          </Field>
          <Field label="local proxy base port">
            <Input value={localProxyPortBase} onChange={(e) => setLocalProxyPortBase(e.target.value)} />
          </Field>
          <ToggleField
            label="production_mode"
            checked={productionMode}
            onChange={setProductionMode}
            hint="生产 gate；bootstrap 两机 demo 默认关闭。"
          />
          <ToggleField
            label="require_session_manifest"
            checked={requireSessionManifest}
            onChange={setRequireSessionManifest}
            hint="只有 fresh session_manifest 可通过校验时才打开。"
          />
          <ToggleField
            label="allow_production_wide_bind"
            checked={allowProductionWideBind}
            onChange={setAllowProductionWideBind}
            hint="公网 0.0.0.0 监听时才需要。"
          />
          <ToggleField
            label="allow_legacy_unary"
            checked={allowLegacyUnary}
            onChange={setAllowLegacyUnary}
            hint="对当前旧 PJC 二进制启用 unary 兼容模式。"
          />
        </div>
      </StepCard>

      <StepCard
        step="4"
        title="双向 role-package export / import"
        description="把远端 Party A / 本地 Party B 的角色目录各自导出为带 hash manifest 的 package，并在对端导入验证，确保双方拿到的是同一组 role 工件。"
        action={undefined}
        result={undefined}
      >
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Card>
            <CardHeader title="Party A package" description="remote Party A role_dir -> package -> local Party B import" />
            <div className="space-y-3">
              <Field label="source_dir">
                <Input value={serverRoleDir} onChange={(e) => setServerRoleDir(e.target.value)} />
              </Field>
              <Field label="package_path">
                <Input value={serverPackagePath} onChange={(e) => setServerPackagePath(e.target.value)} />
              </Field>
              <div className="flex flex-wrap gap-2">
                <Button variant="primary" onClick={() => exportServerPackage.mutate(undefined as never)} loading={exportServerPackage.isPending}>导出 Party A package</Button>
                <Button variant="secondary" onClick={() => importServerPackageOnClient.mutate(undefined as never)} loading={importServerPackageOnClient.isPending} disabled={!serverPackagePath}>Party B 导入</Button>
              </div>
            </div>
            <ResultSummary data={serverPackageResult} />
            <ResultSummary data={clientPackageImportResult} />
          </Card>
          <Card>
            <CardHeader title="Party B package" description="local Party B role_dir -> package -> remote Party A import" />
            <div className="space-y-3">
              <Field label="source_dir">
                <Input value={clientRoleDir} onChange={(e) => setClientRoleDir(e.target.value)} />
              </Field>
              <Field label="package_path">
                <Input value={clientPackagePath} onChange={(e) => setClientPackagePath(e.target.value)} />
              </Field>
              <div className="flex flex-wrap gap-2">
                <Button variant="primary" onClick={() => exportClientPackage.mutate(undefined as never)} loading={exportClientPackage.isPending}>导出 Party B package</Button>
                <Button variant="secondary" onClick={() => importClientPackageOnServer.mutate(undefined as never)} loading={importClientPackageOnServer.isPending} disabled={!clientPackagePath}>Party A 导入</Button>
              </div>
            </div>
            <ResultSummary data={clientPackageResult} />
            <ResultSummary data={serverPackageImportResult} />
          </Card>
        </div>
      </StepCard>

      <StepCard
        step="5"
        title="启动双边角色 + 状态 / 取消"
        description="分别由远端 Party A 面板和本地 Party B 面板启动角色，不再依赖单机 pjc-only；状态查询按真实双机 job_id + role 拉取。"
        action={undefined}
        result={undefined}
      >
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
          <StatTile label="server role" value={<StatusPill kind={inferStatusKind(serverRoleState)}>{serverRoleState ?? "idle"}</StatusPill>} hint={extractPath(serverStatusResult, "log_path") ?? extractNestedPath(serverStartResult, "snapshot.log_path") ?? "role status"} kind={inferStatusKind(serverRoleState)} />
          <StatTile label="client role" value={<StatusPill kind={inferStatusKind(clientRoleState)}>{clientRoleState ?? "idle"}</StatusPill>} hint={extractPath(clientStatusResult, "log_path") ?? extractNestedPath(clientStartResult, "snapshot.log_path") ?? "role status"} kind={inferStatusKind(clientRoleState)} />
          <StatTile label="server pid" value={String(extractPath(serverStatusResult, "pid") ?? extractNestedPath(serverStartResult, "snapshot.pid") ?? "—")} hint="Party A process" kind="info" />
          <StatTile label="client pid" value={String(extractPath(clientStatusResult, "pid") ?? extractNestedPath(clientStartResult, "snapshot.pid") ?? "—")} hint="Party B process" kind="info" />
        </section>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Card>
            <CardHeader title="Party A server role" />
            <div className="space-y-3">
              <Field label="role_dir">
                <Input value={serverRoleDir} onChange={(e) => setServerRoleDir(e.target.value)} />
              </Field>
              <Field label="out_dir">
                <Input value={serverOutDir} onChange={(e) => setServerOutDir(e.target.value)} />
              </Field>
              <div className="flex flex-wrap gap-2">
                <Button variant="primary" onClick={() => startServer.mutate(undefined as never)} loading={startServer.isPending}>启动 server</Button>
                <Button variant="secondary" onClick={() => refreshServerStatus.mutate(undefined as never)} loading={refreshServerStatus.isPending}>刷新状态</Button>
                <Button variant="danger" onClick={() => cancelServer.mutate(undefined as never)} loading={cancelServer.isPending}>取消</Button>
              </div>
            </div>
            <ResultSummary data={serverStartResult} />
            <ResultSummary data={serverStatusResult} />
            <ResultSummary data={serverCancelResult} />
          </Card>
          <Card>
            <CardHeader title="Party B client role" />
            <div className="space-y-3">
              <Field label="role_dir">
                <Input value={clientRoleDir} onChange={(e) => setClientRoleDir(e.target.value)} />
              </Field>
              <Field label="out_dir">
                <Input value={clientOutDir} onChange={(e) => setClientOutDir(e.target.value)} />
              </Field>
              <div className="flex flex-wrap gap-2">
                <Button variant="primary" onClick={() => startClient.mutate(undefined as never)} loading={startClient.isPending}>启动 client</Button>
                <Button variant="secondary" onClick={() => refreshClientStatus.mutate(undefined as never)} loading={refreshClientStatus.isPending}>刷新状态</Button>
                <Button variant="danger" onClick={() => cancelClient.mutate(undefined as never)} loading={cancelClient.isPending}>取消</Button>
              </div>
            </div>
            <ResultSummary data={clientStartResult} />
            <ResultSummary data={clientStatusResult} />
            <ResultSummary data={clientCancelResult} />
          </Card>
        </div>
      </StepCard>

      <StepCard
        step="6"
        title="signed manifest + evidence merge + release gate"
        description="在双机运行完成后签署 Party A / Party B run manifest，校验证据一致性，再把 Party A 的 public_report 送进 release policy gate。TLS diagnostic 和 negative cases 也放在这一屏做收尾验真。"
        action={undefined}
        result={undefined}
      >
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Card>
            <CardHeader title="双机签名与证据输入" />
            <div className="space-y-3">
              <Field label="signing_key_path">
                <Input value={signingKeyPath} onChange={(e) => setSigningKeyPath(e.target.value)} placeholder="签名 key 路径" />
              </Field>
              <Field label="Party A dir / Party B dir">
                <div className="grid grid-cols-1 gap-3">
                  <Input value={partyADir} onChange={(e) => setPartyADir(e.target.value)} placeholder="party_a_dir" />
                  <Input value={partyBDir} onChange={(e) => setPartyBDir(e.target.value)} placeholder="party_b_dir" />
                </div>
              </Field>
              <Field label="input commitment hash / peer hash">
                <div className="grid grid-cols-1 gap-3">
                  <Input value={inputCommitmentSha} onChange={(e) => setInputCommitmentSha(e.target.value)} placeholder="party_a local input_commitment_sha256" />
                  <Input value={peerInputCommitmentSha} onChange={(e) => setPeerInputCommitmentSha(e.target.value)} placeholder="party_b local input_commitment_sha256" />
                </div>
              </Field>
              <Field label="bucket policy hash / peer hash">
                <div className="grid grid-cols-1 gap-3">
                  <Input value={bucketPolicySha} onChange={(e) => setBucketPolicySha(e.target.value)} placeholder="可选" />
                  <Input value={peerBucketPolicySha} onChange={(e) => setPeerBucketPolicySha(e.target.value)} placeholder="可选" />
                </div>
              </Field>
              <Field label="TLS identity / peer identity">
                <div className="grid grid-cols-1 gap-3">
                  <Input value={tlsIdentity} onChange={(e) => setTlsIdentity(e.target.value)} placeholder="party_a tls identity" />
                  <Input value={peerTlsIdentity} onChange={(e) => setPeerTlsIdentity(e.target.value)} placeholder="party_b tls identity" />
                </div>
              </Field>
            </div>
          </Card>
          <Card>
            <CardHeader title="双机结果与 gate 路径" />
            <div className="space-y-3">
              <Field label="Party A result/public/audit">
                <div className="grid grid-cols-1 gap-3">
                  <Input value={serverResultPath} onChange={(e) => setServerResultPath(e.target.value)} placeholder="attribution_result.json" />
                  <Input value={serverPublicReportPath} onChange={(e) => setServerPublicReportPath(e.target.value)} placeholder="public_report.json" />
                  <Input value={serverAuditChainPath} onChange={(e) => setServerAuditChainPath(e.target.value)} placeholder="audit_chain.json" />
                </div>
              </Field>
              <Field label="Party B result/public/audit">
                <div className="grid grid-cols-1 gap-3">
                  <Input value={clientResultPath} onChange={(e) => setClientResultPath(e.target.value)} placeholder="attribution_result.json" />
                  <Input value={clientPublicReportPath} onChange={(e) => setClientPublicReportPath(e.target.value)} placeholder="public_report.json" />
                  <Input value={clientAuditChainPath} onChange={(e) => setClientAuditChainPath(e.target.value)} placeholder="audit_chain.json" />
                </div>
              </Field>
              <Field label="policy gate 附加路径">
                <div className="grid grid-cols-1 gap-3">
                  <Input value={policyAuditLogPath} onChange={(e) => setPolicyAuditLogPath(e.target.value)} placeholder="policy_audit.jsonl" />
                  <Input value={operatorReportPath} onChange={(e) => setOperatorReportPath(e.target.value)} placeholder="operator_report.json" />
                  <Input value={privacyBudgetLedger} onChange={(e) => setPrivacyBudgetLedger(e.target.value)} placeholder="privacy budget ledger" />
                </div>
              </Field>
            </div>
          </Card>
        </div>

        <div className="flex flex-wrap gap-2 mt-4">
          <Button variant="primary" onClick={() => signServerManifest.mutate(undefined as never)} loading={signServerManifest.isPending} disabled={!signingKeyPath}>签 Party A manifest</Button>
          <Button variant="secondary" onClick={() => signClientManifest.mutate(undefined as never)} loading={signClientManifest.isPending} disabled={!signingKeyPath}>签 Party B manifest</Button>
          <Button variant="primary" onClick={() => verifyMerge.mutate(undefined as never)} loading={verifyMerge.isPending}>evidence merge</Button>
          <Button variant="secondary" onClick={() => runReleaseGate.mutate(undefined as never)} loading={runReleaseGate.isPending}>release gate</Button>
          <Button variant="outline" onClick={() => runTlsDiagnostic.mutate(undefined as never)} loading={runTlsDiagnostic.isPending}>TLS diagnostic</Button>
          <Button variant="outline" onClick={() => runNegativeCases.mutate(undefined as never)} loading={runNegativeCases.isPending}>negative cases</Button>
        </div>

        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-4">
          <StatTile label="merge decision" value={<StatusPill kind={inferStatusKind(mergeDecision)}>{mergeDecision ?? "pending"}</StatusPill>} hint={extractReasonCode(evidenceMergeResult) ?? "verify-merge"} kind={inferStatusKind(mergeDecision)} />
          <StatTile label="release decision" value={<StatusPill kind={inferStatusKind(releaseDecision)}>{releaseDecision ?? "pending"}</StatusPill>} hint={extractReasonCode(releaseGateResult) ?? "policy gate"} kind={inferStatusKind(releaseDecision)} />
          <StatTile label="TLS diag" value={<StatusPill kind={inferStatusKind(extractReportDecision(tlsDiagnosticResult))}>{extractReportDecision(tlsDiagnosticResult) ?? "pending"}</StatusPill>} hint={extractReasonCode(tlsDiagnosticResult) ?? "tls diagnostic"} kind={inferStatusKind(extractReportDecision(tlsDiagnosticResult))} />
          <StatTile label="negative cases" value={<StatusPill kind={inferStatusKind(extractReportDecision(negativeCasesResult))}>{extractReportDecision(negativeCasesResult) ?? "pending"}</StatusPill>} hint={extractReasonCode(negativeCasesResult) ?? "negative paths"} kind={inferStatusKind(extractReportDecision(negativeCasesResult))} />
        </section>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-4">
          <ResultSummary data={serverManifestSignResult} />
          <ResultSummary data={clientManifestSignResult} />
          <ResultSummary data={evidenceMergeResult} />
          <ResultSummary data={releaseGateResult} />
          <ResultSummary data={tlsDiagnosticResult} />
          <ResultSummary data={negativeCasesResult} />
        </div>
      </StepCard>

      <Card>
        <CardHeader
          title="结果汇总 / 公网工件"
          description="把公网双机运行的 bucket 结果、public_report、audit_chain、signed manifest、evidence merge 与 release gate 汇总到这一屏。结果优先从 Party B bucket 目录聚合，没有 merged attribution_result.json 时也能直接看。"
          actions={<Button variant="primary" onClick={() => refreshPublicResults.mutate(undefined as never)} loading={refreshPublicResults.isPending}>刷新结果汇总</Button>}
        />
        {publicResultSummary ? (
          <PublicTwoPartyResultsPanel data={publicResultSummary} />
        ) : (
          <EmptyState title="还没有结果汇总" description="完成至少一轮公网双机运行后，点击“刷新结果汇总”读取当前 role_dir / result_dir / signed manifest / merge / gate 工件。" />
        )}
      </Card>
    </div>
  );
}

function StepCard({
  step,
  title,
  description,
  action,
  result,
  children,
}: {
  step: string;
  title: string;
  description: string;
  action?: React.ReactNode;
  result?: StepResult;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader
        title={<span className="inline-flex items-center gap-2"><span className="pill-info">Step {step}</span>{title}</span>}
        description={description}
        actions={action}
      />
      <div className="space-y-4">
        {children}
        {result !== undefined && <ResultSummary data={result} />}
      </div>
    </Card>
  );
}

function ResultSummary({ data }: { data: StepResult }) {
  if (data === undefined) return null;
  if (typeof data === "string") {
    return <ErrorBanner title="响应" message={data} />;
  }
  const decision = extractReportDecision(data) ?? extractDecision(data) ?? extractState(data) ?? extractStatus(data) ?? "ok";
  const reasonCode = extractReasonCode(data);
  const evidencePath = extractPath(data, "evidence_path") ?? extractPath(data, "manifest_path") ?? extractPath(data, "report_path");
  return (
    <div className="space-y-3">
      <KeyValueGrid
        columns={4}
        items={[
          { label: "decision / state", value: <StatusPill kind={inferStatusKind(decision)}>{decision}</StatusPill> },
          { label: "reason_code", value: reasonCode ?? "—" },
          { label: "evidence / report", value: evidencePath ?? "—" },
          { label: "status", value: extractStatus(data) ?? "—" },
        ]}
      />
      <JsonDetails title="原始 JSON" data={data} maxHeight="280px" />
    </div>
  );
}

function PublicTwoPartyResultsPanel({ data }: { data: JsonRecord }) {
  const combined = extractRecord(data, "combined");
  const partyA = extractRecord(data, "party_a");
  const partyB = extractRecord(data, "party_b");
  const evidenceMerge = extractRecord(data, "evidence_merge");
  const releaseGate = extractRecord(data, "release_gate");
  const partyBBuckets = extractRecordArray(partyB, "bucket_results");
  const notes = extractStringArray(combined, "notes");
  const findings = extractStringArray(data, "findings");
  const releaseLabel = extractString(combined, "release_decision") ?? (extractBoolean(combined, "released") === true ? "released" : extractBoolean(combined, "released") === false ? "withheld" : "pending");
  const mergeLabel = extractString(combined, "merge_decision") ?? "pending";

  return (
    <div className="space-y-4">
      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-3">
        <StatTile label="bucket_count" value={formatNumber(extractNumber(combined, "bucket_count"))} hint={extractString(combined, "summary_source") ?? "summary source"} kind="info" />
        <StatTile label="intersection_size_total" value={formatNumber(extractNumber(combined, "intersection_size_total"))} hint="聚合后的交集人数" kind="info" />
        <StatTile label="intersection_sum_total" value={formatNumber(extractNumber(combined, "intersection_sum_total"))} hint="聚合后的 value sum" kind="info" />
        <StatTile label="release" value={<StatusPill kind={inferStatusKind(releaseLabel)}>{releaseLabel}</StatusPill>} hint={extractString(combined, "release_reason_code") ?? "release gate"} kind={inferStatusKind(releaseLabel)} />
        <StatTile label="merge" value={<StatusPill kind={inferStatusKind(mergeLabel)}>{mergeLabel}</StatusPill>} hint={extractString(combined, "merge_reason_code") ?? "evidence merge"} kind={inferStatusKind(mergeLabel)} />
        <StatTile label="artifacts" value={`${formatNumber(extractNumber(combined, "available_artifact_count"))} / ${formatNumber(extractNumber(combined, "missing_artifact_count"))}`} hint={formatTimestamp(extractString(data, "generated_at_utc"))} kind="info" />
      </section>

      {(notes.length > 0 || findings.length > 0) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {notes.length > 0 && (
            <div className="panel-soft rounded-lg p-3">
              <div className="field-label">汇总说明</div>
              <ul className="mt-2 space-y-1 text-2xs text-ink-muted">
                {notes.map((item) => <li key={item}>- {item}</li>)}
              </ul>
            </div>
          )}
          {findings.length > 0 && (
            <div className="panel-soft rounded-lg p-3">
              <div className="field-label">缺失 / 待补工件</div>
              <ul className="mt-2 space-y-1 text-2xs text-ink-muted">
                {findings.map((item) => <li key={item}>- {item}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <PartyArtifactPanel title="Party A 工件" data={partyA} />
        <PartyArtifactPanel title="Party B 工件" data={partyB} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ArtifactPanel title="Evidence Merge" data={evidenceMerge} />
        <ArtifactPanel title="Release Gate" data={releaseGate} />
      </div>

      <Card>
        <CardHeader title="Party B Bucket 结果" description="真实公网双机运行里，最终 PJC 结果通常先落在 Party B client 侧。这里优先展示 bucket_*/attribution_result.json 的聚合结果。" />
        <BucketResultsTable rows={partyBBuckets} />
      </Card>

      <JsonDetails title="查看完整结果摘要 JSON" data={data} maxHeight="360px" />
    </div>
  );
}

function PartyArtifactPanel({ title, data }: { title: string; data: JsonRecord | undefined }) {
  if (!data) {
    return (
      <Card>
        <CardHeader title={title} />
        <EmptyState title="没有结果目录信息" description="当前摘要没有返回这一侧的 role_dir / result_dir。" />
      </Card>
    );
  }
  const artifacts = extractRecord(data, "artifacts");
  const notes = extractStringArray(data, "notes");
  return (
    <Card>
      <CardHeader title={title} description={`${extractString(data, "role_dir") ?? "—"} | ${extractString(data, "result_dir") ?? "—"}`} />
      <div className="space-y-3">
        {notes.length > 0 && (
          <div className="panel-soft rounded-lg p-3 text-2xs text-ink-muted">
            {notes.map((item) => <div key={item}>{item}</div>)}
          </div>
        )}
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
          <ArtifactPanel title="attribution_result" data={extractRecord(artifacts, "attribution_result")} />
          <ArtifactPanel title="public_report" data={extractRecord(artifacts, "public_report")} />
          <ArtifactPanel title="audit_chain" data={extractRecord(artifacts, "audit_chain")} />
          <ArtifactPanel title="signed_manifest" data={extractRecord(artifacts, "signed_manifest")} />
        </div>
      </div>
    </Card>
  );
}

function ArtifactPanel({ title, data }: { title: string; data: JsonRecord | undefined }) {
  const available = extractBoolean(data, "available") === true;
  const summary = extractRecord(data, "summary");
  const verification = extractRecord(data, "verification");
  const payload = data ? data.payload : undefined;
  const statusLabel = available ? artifactStatusLabel(summary) : "missing";
  const metricItems = buildArtifactMetricItems(summary, extractString(data, "sha256"));

  return (
    <div className="panel-soft rounded-lg p-3 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-ink">{title}</div>
          <div className="text-2xs text-ink-muted font-mono break-all mt-1">{extractString(data, "path") ?? "—"}</div>
        </div>
        <StatusPill kind={available ? inferStatusKind(statusLabel) : "muted"}>{statusLabel}</StatusPill>
      </div>
      {metricItems.length > 0 && <KeyValueGrid columns={2} items={metricItems} />}
      {summary && <JsonDetails title="摘要 JSON" data={summary} maxHeight="180px" />}
      {verification && <JsonDetails title="verification JSON" data={verification} maxHeight="180px" />}
      {payload && <JsonDetails title="原始 JSON" data={payload} maxHeight="220px" />}
    </div>
  );
}

function BucketResultsTable({ rows }: { rows: JsonRecord[] }) {
  if (rows.length === 0) {
    return <EmptyState title="没有 bucket 结果" description="当前 role_dir 下还没有读取到 bucket_*/attribution_result.json。" />;
  }
  return (
    <div className="space-y-3">
      <div className="overflow-x-auto">
        <table className="data-grid">
          <thead>
            <tr>
              <th>bucket</th>
              <th>intersection_size</th>
              <th>intersection_sum</th>
              <th>timestamp</th>
              <th>server_addr</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={extractString(row, "path") ?? extractString(row, "bucket") ?? `bucket-row-${index}`}>
                <td className="font-mono text-2xs">{extractString(row, "bucket") ?? "—"}</td>
                <td>{formatNumber(extractNumber(row, "intersection_size"))}</td>
                <td>{formatNumber(extractNumber(row, "intersection_sum"))}</td>
                <td className="text-2xs">{formatTimestamp(extractString(row, "timestamp"))}</td>
                <td className="font-mono text-2xs">{extractString(row, "server_addr") ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <JsonDetails title="查看 bucket 原始 JSON 数组" data={rows} maxHeight="260px" />
    </div>
  );
}

function ToggleField({
  label,
  checked,
  onChange,
  hint,
}: {
  label: string;
  checked: boolean;
  onChange: (next: boolean) => void;
  hint: string;
}) {
  return (
    <Field label={label} hint={hint}>
      <label className="flex items-center gap-2 text-2xs text-ink-muted h-9 px-3 rounded-lg bg-bg-subtle border border-line cursor-pointer">
        <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
        {checked ? "enabled" : "disabled"}
      </label>
    </Field>
  );
}

function buildPreflightPayload(args: {
  jobId: string;
  role: "server" | "client";
  peerHost: string;
  peerPort: number;
  certDir: string;
  serverHostname: string;
  expectedPeerIdentity: string;
  expectedCaFingerprint: string;
  expectedCommit: string;
  helperScriptPath: string;
  pjcBinDir: string;
  inputCsvPath: string;
  inputManifestPath: string;
  outputDir: string;
}): Record<string, Json> {
  return {
    job_id: args.jobId,
    role: args.role,
    peer_host: args.peerHost,
    peer_port: args.peerPort,
    cert_dir: args.certDir,
    server_hostname: args.serverHostname,
    expected_peer_identity: args.expectedPeerIdentity || undefined,
    expected_ca_fingerprint_sha256: args.expectedCaFingerprint || undefined,
    expected_commit: args.expectedCommit || undefined,
    helper_script_path: args.helperScriptPath || undefined,
    pjc_binary_path: args.pjcBinDir ? `${args.pjcBinDir}/private_join_and_compute/client` : undefined,
    input_csv_path: args.inputCsvPath || undefined,
    input_manifest_path: args.inputManifestPath || undefined,
    output_dir: args.outputDir || undefined,
    expected_dataplane_port: args.peerPort,
    require_unique_output: true,
  };
}

function handleTypedError(
  err: ApiError,
  setResult: (data: StepResult) => void,
  toast: ReturnType<typeof useToast>,
  label: string,
) {
  if ([409, 422].includes(err.status) && err.body && typeof err.body === "object") {
    setResult(err.body as Record<string, Json>);
    toast.pushError(`${label} returned ${err.status}`, "已保留 typed report，展开原始 JSON 查看 deny 原因。");
    return;
  }
  toast.pushError(`${label} 失败`, err.message);
}

function numOr(value: string, fallback: number): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function extractStatus(value: StepResult): string | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  return typeof value.status === "string" ? value.status : undefined;
}

function extractDecision(value: StepResult): string | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  return typeof value.decision === "string" ? value.decision : undefined;
}

function extractReportDecision(value: StepResult): string | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const report = value.report;
  if (!report || typeof report !== "object" || Array.isArray(report)) return undefined;
  return typeof report.decision === "string" ? report.decision : undefined;
}

function extractReasonCode(value: StepResult): string | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  if (typeof value.reason_code === "string") return value.reason_code;
  const report = value.report;
  if (!report || typeof report !== "object" || Array.isArray(report)) return undefined;
  return typeof report.reason_code === "string" ? report.reason_code : undefined;
}

function extractState(value: StepResult): string | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  return typeof value.state === "string" ? value.state : undefined;
}

function extractNestedState(value: StepResult): string | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const snapshot = value.snapshot;
  if (!snapshot || typeof snapshot !== "object" || Array.isArray(snapshot)) return undefined;
  return typeof snapshot.state === "string" ? snapshot.state : undefined;
}

function extractPath(value: StepResult, key: string): string | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const next = value[key];
  return typeof next === "string" ? next : undefined;
}

function extractNestedPath(value: StepResult, path: string): string | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  let current: unknown = value;
  for (const segment of path.split(".")) {
    if (!current || typeof current !== "object" || Array.isArray(current)) return undefined;
    current = (current as Record<string, unknown>)[segment];
  }
  return typeof current === "string" ? current : undefined;
}

function extractLogPath(value: StepResult): string | undefined {
  return extractPath(value, "log_path") ?? extractNestedPath(value, "snapshot.log_path");
}

function extractRecord(value: unknown, key: string): JsonRecord | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const next = (value as Record<string, unknown>)[key];
  if (!next || typeof next !== "object" || Array.isArray(next)) return undefined;
  return next as JsonRecord;
}

function extractRecordArray(value: unknown, key: string): JsonRecord[] {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  const next = (value as Record<string, unknown>)[key];
  if (!Array.isArray(next)) return [];
  return next.filter((item): item is JsonRecord => !!item && typeof item === "object" && !Array.isArray(item)) as JsonRecord[];
}

function extractString(value: unknown, key: string): string | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const next = (value as Record<string, unknown>)[key];
  return typeof next === "string" ? next : undefined;
}

function extractNumber(value: unknown, key: string): number | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const next = (value as Record<string, unknown>)[key];
  return typeof next === "number" ? next : undefined;
}

function extractBoolean(value: unknown, key: string): boolean | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const next = (value as Record<string, unknown>)[key];
  return typeof next === "boolean" ? next : undefined;
}

function extractStringArray(value: unknown, key: string): string[] {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  const next = (value as Record<string, unknown>)[key];
  if (!Array.isArray(next)) return [];
  return next.filter((item): item is string => typeof item === "string");
}

function artifactStatusLabel(summary: JsonRecord | undefined): string {
  const decision = extractString(summary, "decision");
  if (decision) return decision;
  const verification = extractString(summary, "verification_status");
  if (verification) return verification;
  const released = extractBoolean(summary, "released");
  if (released === true) return "released";
  if (released === false) return "withheld";
  const party = extractString(summary, "party");
  if (party) return party;
  return "available";
}

function buildArtifactMetricItems(summary: JsonRecord | undefined, sha256: string | undefined) {
  const items: Array<{ label: React.ReactNode; value: React.ReactNode }> = [];
  const intersectionSize = extractNumber(summary, "intersection_size");
  const intersectionSum = extractNumber(summary, "intersection_sum");
  if (intersectionSize !== undefined) items.push({ label: "intersection_size", value: formatNumber(intersectionSize) });
  if (intersectionSum !== undefined) items.push({ label: "intersection_sum", value: formatNumber(intersectionSum) });
  const decision = extractString(summary, "decision") ?? extractString(summary, "party") ?? extractString(summary, "verification_status");
  if (decision) items.push({ label: "decision / role", value: decision });
  const reasonCode = extractString(summary, "reason_code") ?? extractString(summary, "verification_reason_code");
  if (reasonCode) items.push({ label: "reason_code", value: reasonCode });
  const stageCount = extractNumber(summary, "stage_count");
  if (stageCount !== undefined) items.push({ label: "stage_count", value: formatNumber(stageCount) });
  const jobId = extractString(summary, "job_id");
  if (jobId) items.push({ label: "job_id", value: jobId });
  if (sha256) items.push({ label: "sha256", value: shortHash(sha256) });
  return items.slice(0, 4);
}
