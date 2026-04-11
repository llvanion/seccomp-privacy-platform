use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, File};
use std::io::{BufRead, BufReader, Read, Write};
#[cfg(unix)]
use std::os::unix::fs::FileTypeExt;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result, bail};
use clap::{Parser, Subcommand, ValueEnum};
use csv::{ReaderBuilder, StringRecord, WriterBuilder};
use hmac::{Hmac, Mac};
use serde::Serialize;
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};

type HmacSha256 = Hmac<Sha256>;

#[derive(Debug, Clone, Parser)]
#[command(name = "bridge")]
#[command(about = "Generate tokenized PJC inputs from locally exported records.")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Clone, Subcommand)]
enum Command {
    Generate(GenerateArgs),
    PrepareJob(PrepareJobArgs),
}

#[derive(Debug, Clone, Parser)]
struct GenerateArgs {
    #[arg(long)]
    input: PathBuf,

    #[arg(long, value_enum, default_value_t = InputFormat::Csv)]
    input_format: InputFormat,

    #[arg(long)]
    out_dir: PathBuf,

    #[arg(long, value_enum)]
    role: Role,

    #[arg(long)]
    join_key_column: String,

    #[arg(long)]
    value_column: Option<String>,

    #[arg(long, value_enum, default_value_t = ValueMode::Count)]
    value_mode: ValueMode,

    #[arg(long, value_enum, default_value_t = Normalizer::Identity)]
    normalizer: Normalizer,

    #[arg(long)]
    token_scope: String,

    #[arg(long)]
    token_secret: Option<String>,

    #[arg(long)]
    token_secret_env: Option<String>,

    #[arg(long)]
    job_id: String,

    #[arg(long, default_value = "bridge-hmac-sha256-v1")]
    token_scheme: String,

    #[arg(long, default_value = "1")]
    token_key_version: String,

    #[arg(long, default_value = "1")]
    normalize_version: String,

    #[arg(long, default_value = "one_per_user_keep_max_value")]
    dedup_policy: String,

    #[arg(long)]
    production_mode: bool,

    #[arg(long)]
    audit_log: Option<PathBuf>,
}

#[derive(Debug, Clone, Parser)]
struct PrepareJobArgs {
    #[arg(long)]
    server_input: PathBuf,

    #[arg(long, value_enum, default_value_t = InputFormat::Csv)]
    server_input_format: InputFormat,

    #[arg(long)]
    server_join_key_column: String,

    #[arg(long, value_enum, default_value_t = Normalizer::Identity)]
    server_normalizer: Normalizer,

    #[arg(long)]
    client_input: PathBuf,

    #[arg(long, value_enum, default_value_t = InputFormat::Csv)]
    client_input_format: InputFormat,

    #[arg(long)]
    client_join_key_column: String,

    #[arg(long)]
    client_value_column: Option<String>,

    #[arg(long, value_enum, default_value_t = ValueMode::Count)]
    client_value_mode: ValueMode,

    #[arg(long, value_enum, default_value_t = Normalizer::Identity)]
    client_normalizer: Normalizer,

    #[arg(long)]
    out_dir: PathBuf,

    #[arg(long)]
    job_id: String,

    #[arg(long)]
    token_scope: String,

    #[arg(long)]
    token_secret: Option<String>,

    #[arg(long)]
    token_secret_env: Option<String>,

    #[arg(long, default_value = "bridge-hmac-sha256-v1")]
    token_scheme: String,

    #[arg(long, default_value = "1")]
    token_key_version: String,

    #[arg(long, default_value = "1")]
    normalize_version: String,

    #[arg(long, default_value = "one_per_user_keep_max_value")]
    dedup_policy: String,

    #[arg(long)]
    production_mode: bool,

    #[arg(long)]
    audit_log: Option<PathBuf>,
}

#[derive(Debug, Clone, Copy, ValueEnum)]
enum InputFormat {
    Csv,
    Jsonl,
}

#[derive(Debug, Clone, Copy, ValueEnum, Serialize)]
#[serde(rename_all = "snake_case")]
enum Role {
    Server,
    Client,
}

#[derive(Debug, Clone, Copy, ValueEnum, Serialize)]
#[serde(rename_all = "snake_case")]
enum ValueMode {
    Count,
    RawInt,
}

#[derive(Debug, Clone, Copy, ValueEnum, Serialize)]
#[serde(rename_all = "snake_case")]
enum Normalizer {
    Identity,
    Email,
    Phone,
}

#[derive(Debug, Clone)]
struct InputRow {
    join_key: String,
    value: Option<i64>,
}

#[derive(Debug, Clone)]
struct InputSpec {
    input: PathBuf,
    input_format: InputFormat,
    join_key_column: String,
    value_column: Option<String>,
    normalizer: Normalizer,
}

#[derive(Debug, Serialize)]
struct OutputInfo {
    role: Role,
    file: String,
    row_count: usize,
}

#[derive(Debug, Serialize)]
struct SingleJobMeta {
    schema: String,
    job_id: String,
    generator: String,
    role: Role,
    input_file: String,
    input_format: InputFormatSerde,
    join_key_column: String,
    value_column: Option<String>,
    value_mode: ValueMode,
    normalizer: Normalizer,
    normalize_version: String,
    token_scheme: String,
    token_scope: String,
    token_key_version: String,
    dedup_policy: String,
    outputs: Vec<OutputInfo>,
    counts: BTreeMap<String, usize>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "snake_case")]
enum InputFormatSerde {
    Csv,
    Jsonl,
}

fn main() -> Result<()> {
    let cli = Cli::parse();

    match cli.command {
        Command::Generate(args) => run_generate(args),
        Command::PrepareJob(args) => run_prepare_job(args),
    }
}

fn run_generate(args: GenerateArgs) -> Result<()> {
    let production_mode = production_mode_enabled(args.production_mode);
    let token_secret =
        resolve_token_secret(&args.token_secret, &args.token_secret_env, production_mode)?;
    let spec = InputSpec {
        input: args.input.clone(),
        input_format: args.input_format,
        join_key_column: args.join_key_column.clone(),
        value_column: args.value_column.clone(),
        normalizer: args.normalizer,
    };
    let rows = load_rows(&spec, args.role)?;

    if rows.is_empty() {
        bail!("input produced zero usable rows");
    }

    fs::create_dir_all(&args.out_dir).with_context(|| {
        format!(
            "failed to create output directory {}",
            args.out_dir.display()
        )
    })?;

    let (output_info, counts) = match args.role {
        Role::Server => {
            let tokens = build_server_tokens(&rows, &args.token_scope, &token_secret)?;
            let server_path = args.out_dir.join("server.csv");
            write_server_csv(&server_path, &tokens)?;

            let mut counts = BTreeMap::new();
            counts.insert("input_rows".to_string(), rows.len());
            counts.insert("unique_join_tokens".to_string(), tokens.len());

            (
                OutputInfo {
                    role: Role::Server,
                    file: "server.csv".to_string(),
                    row_count: tokens.len(),
                },
                counts,
            )
        }
        Role::Client => {
            let token_values =
                build_client_values(&rows, &args.token_scope, &token_secret, args.value_mode)?;
            let client_path = args.out_dir.join("client.csv");
            write_client_csv(&client_path, &token_values)?;

            let mut counts = BTreeMap::new();
            counts.insert("input_rows".to_string(), rows.len());
            counts.insert("unique_join_tokens".to_string(), token_values.len());

            (
                OutputInfo {
                    role: Role::Client,
                    file: "client.csv".to_string(),
                    row_count: token_values.len(),
                },
                counts,
            )
        }
    };

    let meta = SingleJobMeta {
        schema: "bridge_job_meta/v1".to_string(),
        job_id: args.job_id,
        generator: "bridge-rust-v0".to_string(),
        role: args.role,
        input_file: canonicalize_display(&spec.input)?,
        input_format: input_format_serde(spec.input_format),
        join_key_column: spec.join_key_column,
        value_column: spec.value_column,
        value_mode: args.value_mode,
        normalizer: spec.normalizer,
        normalize_version: args.normalize_version,
        token_scheme: args.token_scheme,
        token_scope: args.token_scope,
        token_key_version: args.token_key_version,
        dedup_policy: args.dedup_policy,
        outputs: vec![output_info],
        counts,
    };

    write_json_pretty(&args.out_dir.join("job_meta.json"), &meta)?;
    let audit_path = args
        .audit_log
        .clone()
        .unwrap_or_else(|| args.out_dir.join("bridge_audit.jsonl"));
    append_bridge_audit(
        &audit_path,
        json!({
            "event": "bridge_generate",
            "job_id": meta.job_id,
            "correlation_id": meta.job_id,
            "role": meta.role,
            "input_file": meta.input_file,
            "input_file_type": path_file_type_label(&spec.input)?,
            "input_sha256": sha256_regular_file_json(&spec.input)?,
            "output_dir": canonicalize_display(&args.out_dir)?,
            "job_meta_sha256": sha256_file(&args.out_dir.join("job_meta.json"))?,
            "outputs": meta.outputs,
            "counts": meta.counts,
            "token_scheme": meta.token_scheme,
            "token_scope": meta.token_scope,
            "token_key_version": meta.token_key_version,
            "normalize_version": meta.normalize_version,
            "dedup_policy": meta.dedup_policy,
            "production_mode": production_mode,
            "token_secret_source": token_secret_source(&args.token_secret, &args.token_secret_env),
            "decision": "allow",
            "reason_code": "ok"
        }),
    )?;
    println!(
        "[ok] wrote bridge outputs under {}",
        args.out_dir
            .canonicalize()
            .unwrap_or(args.out_dir)
            .display()
    );

    Ok(())
}

fn run_prepare_job(args: PrepareJobArgs) -> Result<()> {
    let production_mode = production_mode_enabled(args.production_mode);
    let token_secret =
        resolve_token_secret(&args.token_secret, &args.token_secret_env, production_mode)?;
    let server_spec = InputSpec {
        input: args.server_input.clone(),
        input_format: args.server_input_format,
        join_key_column: args.server_join_key_column.clone(),
        value_column: None,
        normalizer: args.server_normalizer,
    };
    let client_spec = InputSpec {
        input: args.client_input.clone(),
        input_format: args.client_input_format,
        join_key_column: args.client_join_key_column.clone(),
        value_column: args.client_value_column.clone(),
        normalizer: args.client_normalizer,
    };

    let server_rows = load_rows(&server_spec, Role::Server)?;
    let client_rows = load_rows(&client_spec, Role::Client)?;
    if server_rows.is_empty() {
        bail!("server input produced zero usable rows");
    }
    if client_rows.is_empty() {
        bail!("client input produced zero usable rows");
    }

    fs::create_dir_all(&args.out_dir).with_context(|| {
        format!(
            "failed to create output directory {}",
            args.out_dir.display()
        )
    })?;

    let server_tokens = build_server_tokens(&server_rows, &args.token_scope, &token_secret)?;
    let client_values = build_client_values(
        &client_rows,
        &args.token_scope,
        &token_secret,
        args.client_value_mode,
    )?;

    write_server_csv(&args.out_dir.join("server.csv"), &server_tokens)?;
    write_client_csv(&args.out_dir.join("client.csv"), &client_values)?;

    let meta = json!({
        "schema": "bridge_job_meta/v1",
        "job_id": args.job_id,
        "job_type": "bridge_prepared_csv",
        "generator": "bridge-rust-v0",
        "bucket_field": Value::Null,
        "bucket_count": 1,
        "bucket": {
            "field": Value::Null,
            "outputs": []
        },
        "input_sizes": {
            "exposure_n": server_tokens.len(),
            "purchase_n": client_values.len()
        },
        "bridge": {
            "token_scheme": args.token_scheme,
            "token_scope": args.token_scope,
            "token_key_version": args.token_key_version,
            "normalize_version": args.normalize_version,
            "dedup_policy": args.dedup_policy,
            "server": {
                "input_file": canonicalize_display(&server_spec.input)?,
                "input_format": input_format_label(server_spec.input_format),
                "join_key_column": server_spec.join_key_column,
                "normalizer": server_spec.normalizer
            },
            "client": {
                "input_file": canonicalize_display(&client_spec.input)?,
                "input_format": input_format_label(client_spec.input_format),
                "join_key_column": client_spec.join_key_column,
                "value_column": client_spec.value_column,
                "value_mode": args.client_value_mode,
                "normalizer": client_spec.normalizer
            }
        },
        "inputs": {
            "server_csv": canonicalize_display(&args.out_dir.join("server.csv"))?,
            "client_csv": canonicalize_display(&args.out_dir.join("client.csv"))?
        },
        "counts": {
            "server_input_rows": server_rows.len(),
            "client_input_rows": client_rows.len(),
            "server_unique_join_tokens": server_tokens.len(),
            "client_unique_join_tokens": client_values.len()
        }
    });

    write_json_pretty(&args.out_dir.join("job_meta.json"), &meta)?;
    let audit_path = args
        .audit_log
        .clone()
        .unwrap_or_else(|| args.out_dir.join("bridge_audit.jsonl"));
    append_bridge_audit(
        &audit_path,
        json!({
            "event": "bridge_prepare_job",
            "job_id": meta.get("job_id").and_then(Value::as_str).unwrap_or(""),
            "correlation_id": meta.get("job_id").and_then(Value::as_str).unwrap_or(""),
            "server_input_file": canonicalize_display(&server_spec.input)?,
            "server_input_file_type": path_file_type_label(&server_spec.input)?,
            "server_input_sha256": sha256_regular_file_json(&server_spec.input)?,
            "client_input_file": canonicalize_display(&client_spec.input)?,
            "client_input_file_type": path_file_type_label(&client_spec.input)?,
            "client_input_sha256": sha256_regular_file_json(&client_spec.input)?,
            "server_csv": canonicalize_display(&args.out_dir.join("server.csv"))?,
            "server_csv_sha256": sha256_file(&args.out_dir.join("server.csv"))?,
            "client_csv": canonicalize_display(&args.out_dir.join("client.csv"))?,
            "client_csv_sha256": sha256_file(&args.out_dir.join("client.csv"))?,
            "job_meta_file": canonicalize_display(&args.out_dir.join("job_meta.json"))?,
            "job_meta_sha256": sha256_file(&args.out_dir.join("job_meta.json"))?,
            "counts": meta.get("counts").cloned().unwrap_or(Value::Null),
            "token_scheme": meta.pointer("/bridge/token_scheme").and_then(Value::as_str).unwrap_or(""),
            "token_scope": meta.pointer("/bridge/token_scope").and_then(Value::as_str).unwrap_or(""),
            "token_key_version": meta.pointer("/bridge/token_key_version").and_then(Value::as_str).unwrap_or(""),
            "normalize_version": meta.pointer("/bridge/normalize_version").and_then(Value::as_str).unwrap_or(""),
            "dedup_policy": meta.pointer("/bridge/dedup_policy").and_then(Value::as_str).unwrap_or(""),
            "production_mode": production_mode,
            "token_secret_source": token_secret_source(&args.token_secret, &args.token_secret_env),
            "decision": "allow",
            "reason_code": "ok"
        }),
    )?;
    println!(
        "[ok] wrote paired job under {}",
        args.out_dir
            .canonicalize()
            .unwrap_or(args.out_dir)
            .display()
    );

    Ok(())
}

fn production_mode_enabled(flag: bool) -> bool {
    flag || std::env::var("BRIDGE_PRODUCTION_MODE")
        .map(|value| matches!(value.as_str(), "1" | "true" | "TRUE" | "yes" | "YES"))
        .unwrap_or(false)
}

fn resolve_token_secret(
    secret: &Option<String>,
    secret_env: &Option<String>,
    production_mode: bool,
) -> Result<String> {
    if production_mode && secret.is_some() {
        bail!("--token-secret is forbidden in production mode; use --token-secret-env");
    }
    match (secret, secret_env) {
        (Some(secret), None) => {
            if secret.is_empty() {
                bail!("token secret cannot be empty");
            }
            Ok(secret.clone())
        }
        (None, Some(env_name)) => {
            let value = std::env::var(env_name).with_context(|| {
                format!("failed to read token secret from env var {}", env_name)
            })?;
            if value.is_empty() {
                bail!("token secret from env var {} cannot be empty", env_name);
            }
            Ok(value)
        }
        (Some(_), Some(_)) => bail!("use either --token-secret or --token-secret-env, not both"),
        (None, None) => bail!("missing token secret: set --token-secret or --token-secret-env"),
    }
}

fn token_secret_source(secret: &Option<String>, secret_env: &Option<String>) -> Value {
    match (secret, secret_env) {
        (Some(_), None) => json!({"kind": "cli"}),
        (None, Some(env_name)) => json!({"kind": "env", "name": env_name}),
        _ => json!({"kind": "unknown"}),
    }
}

fn load_rows(spec: &InputSpec, role: Role) -> Result<Vec<InputRow>> {
    match spec.input_format {
        InputFormat::Csv => load_rows_from_csv(spec, role),
        InputFormat::Jsonl => load_rows_from_jsonl(spec, role),
    }
}

fn load_rows_from_csv(spec: &InputSpec, role: Role) -> Result<Vec<InputRow>> {
    let mut reader = ReaderBuilder::new()
        .flexible(true)
        .from_path(&spec.input)
        .with_context(|| format!("failed to open CSV {}", spec.input.display()))?;

    let headers = reader
        .headers()
        .with_context(|| format!("failed to read CSV headers from {}", spec.input.display()))?
        .clone();

    let join_idx = find_header_index(&headers, &spec.join_key_column)?;
    let value_idx = match role {
        Role::Client => spec
            .value_column
            .as_ref()
            .map(|name| find_header_index(&headers, name))
            .transpose()?,
        Role::Server => None,
    };

    let mut rows = Vec::new();
    for record in reader.records() {
        let record = record?;
        if let Some(row) = row_from_csv_record(&record, join_idx, value_idx, spec.normalizer)? {
            rows.push(row);
        }
    }
    Ok(rows)
}

fn load_rows_from_jsonl(spec: &InputSpec, role: Role) -> Result<Vec<InputRow>> {
    let file = File::open(&spec.input)
        .with_context(|| format!("failed to open JSONL {}", spec.input.display()))?;
    let reader = BufReader::new(file);
    let mut rows = Vec::new();

    for (line_no, line) in reader.lines().enumerate() {
        let line = line.with_context(|| format!("failed reading line {}", line_no + 1))?;
        if line.trim().is_empty() {
            continue;
        }

        let value: Value = serde_json::from_str(&line)
            .with_context(|| format!("invalid JSON on line {}", line_no + 1))?;
        let value_field = match role {
            Role::Client => spec.value_column.as_deref(),
            Role::Server => None,
        };

        if let Some(row) =
            row_from_json_value(&value, spec.normalizer, &spec.join_key_column, value_field)?
        {
            rows.push(row);
        }
    }

    Ok(rows)
}

fn row_from_csv_record(
    record: &StringRecord,
    join_idx: usize,
    value_idx: Option<usize>,
    normalizer: Normalizer,
) -> Result<Option<InputRow>> {
    let Some(raw_join_key) = record.get(join_idx) else {
        return Ok(None);
    };
    let Some(join_key) = normalize_join_key(raw_join_key, normalizer) else {
        return Ok(None);
    };

    let value = value_idx
        .and_then(|idx| record.get(idx))
        .map(parse_i64)
        .transpose()?;

    Ok(Some(InputRow { join_key, value }))
}

fn row_from_json_value(
    value: &Value,
    normalizer: Normalizer,
    join_key_field: &str,
    value_field: Option<&str>,
) -> Result<Option<InputRow>> {
    let object = value
        .as_object()
        .with_context(|| "each JSONL row must be a JSON object".to_string())?;

    let Some(raw_join_key) = get_json_string(object, join_key_field) else {
        return Ok(None);
    };
    let Some(join_key) = normalize_join_key(raw_join_key, normalizer) else {
        return Ok(None);
    };

    let value = value_field
        .and_then(|field| object.get(field))
        .map(parse_json_i64)
        .transpose()?;

    Ok(Some(InputRow { join_key, value }))
}

fn build_server_tokens(
    rows: &[InputRow],
    token_scope: &str,
    token_secret: &str,
) -> Result<BTreeSet<String>> {
    let mut tokens = BTreeSet::new();
    for row in rows {
        tokens.insert(join_token(&row.join_key, token_scope, token_secret)?);
    }
    Ok(tokens)
}

fn build_client_values(
    rows: &[InputRow],
    token_scope: &str,
    token_secret: &str,
    value_mode: ValueMode,
) -> Result<BTreeMap<String, i64>> {
    let mut token_values = BTreeMap::new();
    for row in rows {
        let token = join_token(&row.join_key, token_scope, token_secret)?;
        let value = client_value_for_row(row, value_mode)?;
        match token_values.get_mut(&token) {
            Some(existing) => {
                if value > *existing {
                    *existing = value;
                }
            }
            None => {
                token_values.insert(token, value);
            }
        }
    }
    Ok(token_values)
}

fn write_server_csv(path: &Path, tokens: &BTreeSet<String>) -> Result<()> {
    let mut writer = WriterBuilder::new()
        .has_headers(false)
        .from_path(path)
        .with_context(|| format!("failed to open {}", path.display()))?;
    for token in tokens {
        writer.write_record([token])?;
    }
    writer.flush()?;
    Ok(())
}

fn write_client_csv(path: &Path, token_values: &BTreeMap<String, i64>) -> Result<()> {
    let mut writer = WriterBuilder::new()
        .has_headers(false)
        .from_path(path)
        .with_context(|| format!("failed to open {}", path.display()))?;
    for (token, value) in token_values {
        writer.write_record([token, &value.to_string()])?;
    }
    writer.flush()?;
    Ok(())
}

fn write_json_pretty<T: Serialize>(path: &Path, value: &T) -> Result<()> {
    let mut file =
        File::create(path).with_context(|| format!("failed to create {}", path.display()))?;
    serde_json::to_writer_pretty(&mut file, value)?;
    file.write_all(b"\n")?;
    Ok(())
}

fn append_bridge_audit(path: &Path, mut record: Value) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .with_context(|| format!("failed to create audit directory {}", parent.display()))?;
    }
    let object = record
        .as_object_mut()
        .with_context(|| "bridge audit record must be a JSON object".to_string())?;
    object.insert(
        "schema".to_string(),
        Value::String("bridge_audit/v1".to_string()),
    );
    object.insert("ts_unix_ms".to_string(), json!(unix_epoch_ms()?));
    let mut file = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .with_context(|| format!("failed to open bridge audit log {}", path.display()))?;
    serde_json::to_writer(&mut file, &record)?;
    file.write_all(b"\n")?;
    Ok(())
}

fn unix_epoch_ms() -> Result<u128> {
    Ok(SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .context("system clock is before UNIX_EPOCH")?
        .as_millis())
}

fn sha256_file(path: &Path) -> Result<String> {
    let mut file =
        File::open(path).with_context(|| format!("failed to open {}", path.display()))?;
    let mut hasher = Sha256::new();
    let mut buf = [0_u8; 1024 * 64];
    loop {
        let n = file
            .read(&mut buf)
            .with_context(|| format!("failed to read {}", path.display()))?;
        if n == 0 {
            break;
        }
        hasher.update(&buf[..n]);
    }
    Ok(hex_encode(&hasher.finalize()))
}

fn sha256_regular_file_json(path: &Path) -> Result<Value> {
    if path_file_type_label(path)? != "file" {
        return Ok(Value::Null);
    }
    Ok(json!(sha256_file(path)?))
}

fn path_file_type_label(path: &Path) -> Result<&'static str> {
    let file_type = fs::metadata(path)
        .with_context(|| format!("failed to stat {}", path.display()))?
        .file_type();
    if file_type.is_file() {
        return Ok("file");
    }
    #[cfg(unix)]
    {
        if file_type.is_fifo() {
            return Ok("fifo");
        }
    }
    Ok("other")
}

fn normalize_join_key(raw: &str, normalizer: Normalizer) -> Option<String> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return None;
    }

    match normalizer {
        Normalizer::Identity => Some(trimmed.to_string()),
        Normalizer::Email => Some(trimmed.to_ascii_lowercase()),
        Normalizer::Phone => normalize_phone(trimmed),
    }
}

fn normalize_phone(raw: &str) -> Option<String> {
    let mut out = String::new();
    for (idx, ch) in raw.chars().enumerate() {
        if ch.is_ascii_digit() {
            out.push(ch);
        } else if ch == '+' && idx == 0 {
            out.push(ch);
        }
    }

    if out.is_empty() {
        return None;
    }

    if out.starts_with("00") {
        return Some(format!("+{}", &out[2..]));
    }

    if out.starts_with('+') {
        return Some(out);
    }

    Some(out)
}

fn join_token(join_key: &str, token_scope: &str, token_secret: &str) -> Result<String> {
    let mut mac = HmacSha256::new_from_slice(token_secret.as_bytes())
        .context("failed to initialize HMAC-SHA256")?;
    mac.update(join_key.as_bytes());
    mac.update(b"\n");
    mac.update(token_scope.as_bytes());
    let digest = mac.finalize().into_bytes();
    Ok(hex_encode(&digest))
}

fn client_value_for_row(row: &InputRow, value_mode: ValueMode) -> Result<i64> {
    match value_mode {
        ValueMode::Count => Ok(1),
        ValueMode::RawInt => row.value.with_context(|| {
            "client role with value-mode raw-int requires --value-column".to_string()
        }),
    }
}

fn find_header_index(headers: &StringRecord, name: &str) -> Result<usize> {
    headers
        .iter()
        .position(|header| header == name)
        .with_context(|| format!("missing required column {}", name))
}

fn parse_i64(raw: &str) -> Result<i64> {
    raw.trim()
        .parse::<i64>()
        .with_context(|| format!("failed to parse integer value from {}", raw))
}

fn parse_json_i64(value: &Value) -> Result<i64> {
    if let Some(n) = value.as_i64() {
        return Ok(n);
    }
    if let Some(s) = value.as_str() {
        return parse_i64(s);
    }
    bail!("unsupported JSON integer value: {}", value)
}

fn get_json_string<'a>(object: &'a Map<String, Value>, field: &str) -> Option<&'a str> {
    object.get(field)?.as_str()
}

fn canonicalize_display(path: &Path) -> Result<String> {
    Ok(path
        .canonicalize()
        .unwrap_or_else(|_| path.to_path_buf())
        .display()
        .to_string())
}

fn input_format_serde(input_format: InputFormat) -> InputFormatSerde {
    match input_format {
        InputFormat::Csv => InputFormatSerde::Csv,
        InputFormat::Jsonl => InputFormatSerde::Jsonl,
    }
}

fn input_format_label(input_format: InputFormat) -> &'static str {
    match input_format {
        InputFormat::Csv => "csv",
        InputFormat::Jsonl => "jsonl",
    }
}

fn hex_encode(bytes: &[u8]) -> String {
    const LUT: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        out.push(LUT[(byte >> 4) as usize] as char);
        out.push(LUT[(byte & 0x0f) as usize] as char);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn email_normalizer_lowercases_and_trims() {
        let out = normalize_join_key("  Foo.Bar@Example.COM ", Normalizer::Email);
        assert_eq!(out.as_deref(), Some("foo.bar@example.com"));
    }

    #[test]
    fn phone_normalizer_strips_separators() {
        let out = normalize_join_key(" +86 138-0013-8000 ", Normalizer::Phone);
        assert_eq!(out.as_deref(), Some("+8613800138000"));
    }

    #[test]
    fn join_token_is_deterministic() {
        let a = join_token("alice@example.com", "job-1", "secret").unwrap();
        let b = join_token("alice@example.com", "job-1", "secret").unwrap();
        let c = join_token("alice@example.com", "job-2", "secret").unwrap();
        assert_eq!(a, b);
        assert_ne!(a, c);
    }

    #[test]
    fn raw_int_mode_requires_value() {
        let row = InputRow {
            join_key: "user".to_string(),
            value: None,
        };
        assert!(client_value_for_row(&row, ValueMode::RawInt).is_err());
    }

    #[test]
    fn client_values_keep_max_per_token() {
        let rows = vec![
            InputRow {
                join_key: "alice@example.com".to_string(),
                value: Some(3),
            },
            InputRow {
                join_key: "alice@example.com".to_string(),
                value: Some(8),
            },
        ];
        let out = build_client_values(&rows, "job", "secret", ValueMode::RawInt).unwrap();
        assert_eq!(out.len(), 1);
        assert_eq!(out.values().next().copied(), Some(8));
    }
}
