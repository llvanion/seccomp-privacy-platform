#!/usr/bin/env bash

resolve_path_under_module_root() {
  local module_root="$1"
  local raw="$2"
  case "$raw" in
    /*) printf '%s\n' "$raw" ;;
    *) printf '%s\n' "$module_root/$raw" ;;
  esac
}

resolve_pjc_bin_dir_with_gate() {
  local module_root="$1"
  local workspace_raw="$2"
  local requested_raw="$3"
  local out_dir="$4"
  local chunk_elements="$5"
  local workspace
  workspace="$(resolve_path_under_module_root "$module_root" "$workspace_raw")"
  local gate_py="$module_root/../scripts/check_pjc_binary_capability_gate.py"
  local report_path="$out_dir/pjc_binary_capability_gate.json"
  local cmd=(python3 "$gate_py" --workspace "$workspace" --out "$report_path" --print-resolved-bin-dir)
  if [[ -n "$requested_raw" ]]; then
    cmd+=(--requested-bin-dir "$(resolve_path_under_module_root "$module_root" "$requested_raw")")
  fi
  if [[ "$chunk_elements" != "0" ]]; then
    cmd+=(--require-streaming)
  fi
  "${cmd[@]}"
}
