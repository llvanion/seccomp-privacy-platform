# S7/K3 Live Evidence Report

Generated local verification date: 2026-05-20

This document is the Markdown source record for the completed S7 public-network
two-party PJC mTLS validation and the K3 internal security probe. Keep this file
as the working evidence narrative. The LaTeX/PDF report should be regenerated
only after the Markdown evidence set is stable.

## Scope

The completed live validation used two parties:

- Party A: public VPS endpoint `118.190.61.66:10502`
- Party B: local workstation client

The K3 probe scope was intentionally non-destructive:

- TCP reachability probe
- TLS probe without a client certificate
- verbose TLS probe without a client certificate
- malformed plaintext connection probe

The K3 probe did not include DoS, brute force, credential attacks, traffic
flooding, vulnerability exploitation, or third-party external penetration
testing.

## S7 Result

S7 public-network two-host PJC mTLS validation completed successfully.

Observed PJC result:

```json
{
  "server_addr": "118.190.61.66:10502",
  "tls": true,
  "intersection_size": 2,
  "intersection_sum": 425
}
```

Evidence directory:

```text
tmp/pjc_mtls_cross-vps-005/
```

Primary evidence:

| Item | Result | Evidence |
| --- | --- | --- |
| Party B attribution result | `tls=true`, `intersection_size=2`, `intersection_sum=425` | `tmp/pjc_mtls_cross-vps-005/party_b_client/attribution_result.json` |
| Party A server log | protocol completed and server shut down | `tmp/pjc_mtls_cross-vps-005/party_a_server/server.log` |
| Party B client log | client decrypted intersection result `2 / 425` | `tmp/pjc_mtls_cross-vps-005/party_b_client/client.log` |
| Server TLS identity | `decision=allow`, expected fingerprint matched | `tmp/pjc_mtls_cross-vps-005/server_tls_identity.json` |
| Client TLS identity | `decision=allow`, expected fingerprint matched | `tmp/pjc_mtls_cross-vps-005/client_tls_identity.json` |

## K3 Internal Security Probe Result

K3 internal probe completed with no critical or high findings in the current
non-destructive scope.

Observed assessment:

```json
{
  "critical_findings": 0,
  "high_findings": 0,
  "no_client_certificate_tls_handshake": "not_completed"
}
```

Evidence directory:

```text
tmp/k3_internal_security_cross-vps-005/
```

The verbose no-client-certificate TLS probe did not complete a TLS handshake.
The log records:

- `no peer certificate available`
- `Cipher is (NONE)`
- `unexpected eof while reading`
- fatal TLS alert `decode_error`

This means the unauthenticated TLS probe did not reach the PJC/gRPC application
protocol and did not produce any PJC result.

Primary evidence:

| Item | Result | Evidence |
| --- | --- | --- |
| K3 probe summary | critical/high findings both 0 | `tmp/k3_internal_security_cross-vps-005/probe_summary.json` |
| Security test scope | non-destructive internal probe scope recorded | `tmp/k3_internal_security_cross-vps-005/SECURITY_TEST_SCOPE.md` |
| Findings | no critical/high/medium findings recorded | `tmp/k3_internal_security_cross-vps-005/FINDINGS.md` |
| Verbose no-client-cert TLS log | handshake not completed | `tmp/k3_internal_security_cross-vps-005/tls_probe_no_client_cert_verbose.log` |
| K3 evidence summary | summary and hashes recorded | `tmp/k3_internal_security_cross-vps-005/EVIDENCE_SUMMARY.md` |

## Local Evidence Integrity Verification

The local offline verification script is:

```bash
python3 scripts/verify_s7_k3_evidence_package.py
```

The script checks:

- required evidence files exist
- JSON evidence is parseable
- S7 result fields match the observed public-network run
- server and client TLS identity decisions are `allow`
- server and client logs contain the expected success phrases
- K3 critical/high finding counts are 0
- no-client-certificate TLS handshake is recorded as `not_completed`
- verbose TLS log contains the expected failure evidence
- final SHA-256 evidence hash manifest is regenerated

Latest local run:

```json
{
  "status": "pass",
  "output": "tmp/k3_internal_security_cross-vps-005/evidence_integrity_report.json",
  "checks": 23
}
```

Generated verification artifacts:

| Artifact | Path |
| --- | --- |
| JSON integrity report | `tmp/k3_internal_security_cross-vps-005/evidence_integrity_report.json` |
| Markdown integrity report | `tmp/k3_internal_security_cross-vps-005/evidence_integrity_report.md` |
| Final SHA-256 manifest | `tmp/k3_internal_security_cross-vps-005/final_evidence_hashes.sha256` |

## Report Status Language

Use the following status language in the final report:

- S7 technical validation: completed
- K3 internal security probe: completed
- Evidence integrity check: completed
- Third-party external penetration test: not executed

Do not describe the K3 internal security probe as a third-party external
penetration test. It is an internal, non-destructive black-box probe over the
explicit scope listed above.

## Final Report Insert Notes

When the final LaTeX/PDF report is generated, include this evidence as a
dedicated section near the benchmark and validation evidence area. The section
should cite the evidence directories and state the limitation that formal
third-party external penetration testing is still future work.
