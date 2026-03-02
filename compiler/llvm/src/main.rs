use anyhow::{bail, Context, Result};
use async_recursion::async_recursion;
use axum::body::Bytes;
use axum::extract::State;
use axum::http::{HeaderMap, Method, StatusCode, Uri};
use axum::response::{IntoResponse, Response};
use axum::routing::any;
use axum::{Json, Router};
use clap::{Args, Parser, Subcommand};
use reqwest::header::{HeaderName, HeaderValue};
use rusqlite::types::{Value as SqlValue, ValueRef};
use rusqlite::{params_from_iter, Connection};
use scraper::{Html, Selector};
use serde::Deserialize;
use serde_json::{json, Map, Value};
use std::collections::{HashMap, HashSet};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::Mutex;
use url::form_urlencoded;

#[derive(Parser, Debug)]
#[command(name = "nova-llvm", version = "0.1.4")]
struct Cli {
    #[command(subcommand)]
    command: Option<Command>,
    #[arg(long)]
    ir: Option<PathBuf>,
    #[arg(long, default_value_t = 3000)]
    port: u16,
    #[arg(long = "cap")]
    caps: Vec<String>,
    #[arg(long, default_value = ".")]
    root: PathBuf,
}

#[derive(Subcommand, Debug)]
enum Command {
    Build(BuildArgs),
    Serve(ServeArgs),
}

#[derive(Args, Debug)]
struct BuildArgs {
    #[arg(long)]
    ir: PathBuf,
    #[arg(long)]
    out: PathBuf,
}

#[derive(Args, Debug, Clone)]
struct ServeArgs {
    #[arg(long)]
    ir: Option<PathBuf>,
    #[arg(long, default_value_t = 3000)]
    port: u16,
    #[arg(long = "cap")]
    caps: Vec<String>,
    #[arg(long, default_value = ".")]
    root: PathBuf,
}

#[derive(Debug, Clone, Deserialize)]
struct IrMdl {
    #[serde(default)]
    irv: String,
    #[serde(default)]
    n: String,
    #[serde(default)]
    v: String,
    #[serde(default)]
    rte: Vec<IrRte>,
    #[serde(default)]
    b: Vec<Value>,
}

#[derive(Debug, Clone, Deserialize)]
struct IrRte {
    #[serde(default)]
    m: String,
    #[serde(default)]
    p: String,
    #[serde(default)]
    f: String,
    #[serde(default)]
    b: Vec<Value>,
}

#[derive(Debug, Clone)]
struct RtError {
    code: String,
    msg: String,
    status: StatusCode,
}

impl RtError {
    fn new(code: impl Into<String>, msg: impl Into<String>, status: StatusCode) -> Self {
        Self {
            code: code.into(),
            msg: msg.into(),
            status,
        }
    }
}

#[derive(Default)]
struct DbState {
    seq: u64,
    handles: HashMap<u64, PathBuf>,
}

#[derive(Clone)]
struct AppState {
    ir: Arc<IrMdl>,
    caps: Arc<HashSet<String>>,
    root: Arc<PathBuf>,
    db: Arc<Mutex<DbState>>,
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Some(Command::Build(args)) => cmd_build(args)?,
        Some(Command::Serve(args)) => cmd_serve(args).await?,
        None => {
            let args = ServeArgs {
                ir: cli.ir,
                port: cli.port,
                caps: cli.caps,
                root: cli.root,
            };
            cmd_serve(args).await?;
        }
    }
    Ok(())
}

fn cmd_build(args: BuildArgs) -> Result<()> {
    let exe = env::current_exe().context("cannot resolve current executable")?;
    let out_path = args.out;
    if let Some(parent) = out_path.parent() {
        fs::create_dir_all(parent)
            .with_context(|| format!("cannot create {}", parent.display()))?;
    }

    fs::copy(&exe, &out_path)
        .with_context(|| format!("cannot copy runtime binary to {}", out_path.display()))?;
    let sidecar = sidecar_path(&out_path);
    fs::copy(&args.ir, &sidecar).with_context(|| {
        format!(
            "cannot copy ir '{}' -> '{}'",
            args.ir.display(),
            sidecar.display()
        )
    })?;

    println!(
        "build ok out={} ir={}",
        out_path.display(),
        sidecar.display()
    );
    Ok(())
}

async fn cmd_serve(args: ServeArgs) -> Result<()> {
    let ir_path = resolve_ir_path(args.ir)?;
    let ir = load_ir(&ir_path)?;
    let caps = normalize_caps(&args.caps);
    let root = args
        .root
        .canonicalize()
        .unwrap_or_else(|_| args.root.clone());

    if ir.rte.is_empty() {
        let result = run_script(&ir, &caps, &root).await;
        match result {
            Ok(value) => {
                println!("{}", serde_json::to_string(&value)?);
                return Ok(());
            }
            Err(err) => {
                let payload = json!({"ok": false, "error": {"code": err.code, "msg": err.msg}});
                println!("{}", serde_json::to_string(&payload)?);
                std::process::exit(1);
            }
        }
    }

    let state = AppState {
        ir: Arc::new(ir),
        caps: Arc::new(caps),
        root: Arc::new(root),
        db: Arc::new(Mutex::new(DbState::default())),
    };

    let app = Router::new()
        .fallback(any(dispatch))
        .with_state(state.clone());
    let listener = tokio::net::TcpListener::bind(("0.0.0.0", args.port))
        .await
        .with_context(|| format!("cannot bind 0.0.0.0:{}", args.port))?;
    println!("nova-llvm listening on http://0.0.0.0:{}", args.port);
    axum::serve(listener, app)
        .await
        .context("axum serve failed")?;
    Ok(())
}

fn load_ir(path: &Path) -> Result<IrMdl> {
    let text =
        fs::read_to_string(path).with_context(|| format!("cannot read ir: {}", path.display()))?;
    let mut ir: IrMdl = serde_json::from_str(&text).context("invalid IR JSON")?;
    if ir.irv.is_empty() {
        ir.irv = "0.1.3".to_string();
    }
    Ok(ir)
}

fn resolve_ir_path(explicit: Option<PathBuf>) -> Result<PathBuf> {
    if let Some(path) = explicit {
        return Ok(path);
    }
    let exe = env::current_exe().context("cannot resolve current executable")?;
    let sidecar = sidecar_path(&exe);
    if sidecar.exists() {
        return Ok(sidecar);
    }
    bail!("missing --ir and no sidecar file found for executable");
}

fn sidecar_path(bin: &Path) -> PathBuf {
    let file_name = bin
        .file_name()
        .map(|name| name.to_string_lossy().to_string())
        .unwrap_or_else(|| "app".to_string());
    bin.with_file_name(format!("{file_name}.ir.json"))
}

fn normalize_caps(items: &[String]) -> HashSet<String> {
    items
        .iter()
        .map(|item| item.trim().to_lowercase())
        .filter(|item| !item.is_empty())
        .collect()
}

async fn dispatch(
    State(state): State<AppState>,
    method: Method,
    uri: Uri,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    let req_path = normalize_path(uri.path());
    let mut method_allowed = false;

    for route in &state.ir.rte {
        let Some(params) = match_route_path(&route.p, &req_path) else {
            continue;
        };

        let route_method = normalize_method(&route.m);
        if route_method != method.as_str() {
            method_allowed = true;
            continue;
        }

        let query = parse_query(uri.query().unwrap_or(""));
        let hdrs = parse_headers(&headers);
        let body_text = String::from_utf8_lossy(&body).to_string();
        let result =
            execute_route(&state, route, params, query, hdrs, Value::String(body_text)).await;

        return match result {
            Ok((status, payload)) => json_response(status, payload),
            Err(err) => {
                let payload = json!({"ok": false, "error": {"code": err.code, "msg": err.msg}});
                json_response(err.status, payload)
            }
        };
    }

    if method_allowed {
        return json_response(
            StatusCode::METHOD_NOT_ALLOWED,
            json!({"ok": false, "error": {"code": "METHOD_NOT_ALLOWED", "msg": "method not allowed"}}),
        );
    }

    json_response(
        StatusCode::NOT_FOUND,
        json!({"ok": false, "error": {"code": "ROUTE_NOT_FOUND", "msg": "route not found"}}),
    )
}

fn json_response(status: StatusCode, payload: Value) -> Response {
    (status, Json(payload)).into_response()
}

async fn run_script(
    ir: &IrMdl,
    caps: &HashSet<String>,
    root: &Path,
) -> std::result::Result<Value, RtError> {
    let state = AppState {
        ir: Arc::new(ir.clone()),
        caps: Arc::new(caps.clone()),
        root: Arc::new(root.to_path_buf()),
        db: Arc::new(Mutex::new(DbState::default())),
    };
    let mut env = Map::new();
    env.insert("q".to_string(), Value::Object(Map::new()));
    env.insert("p".to_string(), Value::Object(Map::new()));
    env.insert("h".to_string(), Value::Object(Map::new()));
    env.insert("b".to_string(), Value::String(String::new()));
    env.insert(
        "ctx".to_string(),
        json!({"q": {}, "p": {}, "h": {}, "b": ""}),
    );

    let required = required_caps_from_body(&ir.b);
    ensure_caps(caps, &required)?;

    for stmt in &ir.b {
        let kind = stmt.get("k").and_then(Value::as_str).unwrap_or_default();
        match kind {
            "let" => {
                let name = stmt.get("n").and_then(Value::as_str).ok_or_else(|| {
                    RtError::new(
                        "IR_INVALID",
                        "let missing name",
                        StatusCode::INTERNAL_SERVER_ERROR,
                    )
                })?;
                let value = eval_expr(
                    stmt.get("v").unwrap_or(&Value::Null),
                    &mut env,
                    &state,
                    caps,
                )
                .await?;
                env.insert(name.to_string(), value);
            }
            "cap" => {}
            "call" => {
                let _ = eval_expr(stmt, &mut env, &state, caps).await?;
            }
            "rst.ok" => {
                let value = eval_expr(
                    stmt.get("v").unwrap_or(&Value::Null),
                    &mut env,
                    &state,
                    caps,
                )
                .await?;
                return Ok(value);
            }
            "rst.err" => {
                let value = eval_expr(
                    stmt.get("v").unwrap_or(&Value::Null),
                    &mut env,
                    &state,
                    caps,
                )
                .await?;
                let err = normalize_err_value(&value);
                return Err(RtError::new(
                    err.get("code")
                        .and_then(Value::as_str)
                        .unwrap_or("BAD_REQUEST"),
                    err.get("msg").and_then(Value::as_str).unwrap_or("error"),
                    status_for_code(
                        err.get("code")
                            .and_then(Value::as_str)
                            .unwrap_or("BAD_REQUEST"),
                    ),
                ));
            }
            _ => {
                return Err(RtError::new(
                    "IR_INVALID",
                    format!("unsupported stmt kind '{kind}'"),
                    StatusCode::INTERNAL_SERVER_ERROR,
                ));
            }
        }
    }

    Ok(Value::Null)
}

async fn execute_route(
    state: &AppState,
    route: &IrRte,
    params: Map<String, Value>,
    query: Map<String, Value>,
    headers: Map<String, Value>,
    body: Value,
) -> std::result::Result<(StatusCode, Value), RtError> {
    let required = required_caps_from_body(&route.b);
    ensure_caps(&state.caps, &required)?;

    let mut env = Map::new();
    env.insert("q".to_string(), Value::Object(query.clone()));
    env.insert("p".to_string(), Value::Object(params.clone()));
    env.insert("h".to_string(), Value::Object(headers.clone()));
    env.insert("b".to_string(), body.clone());
    env.insert(
        "ctx".to_string(),
        json!({"q": query, "p": params, "h": headers, "b": body}),
    );

    for stmt in &route.b {
        let kind = stmt.get("k").and_then(Value::as_str).unwrap_or_default();
        match kind {
            "let" => {
                let name = stmt.get("n").and_then(Value::as_str).ok_or_else(|| {
                    RtError::new(
                        "IR_INVALID",
                        "let missing name",
                        StatusCode::INTERNAL_SERVER_ERROR,
                    )
                })?;
                let value = eval_expr(
                    stmt.get("v").unwrap_or(&Value::Null),
                    &mut env,
                    state,
                    &state.caps,
                )
                .await?;
                env.insert(name.to_string(), value);
            }
            "cap" => {}
            "call" => {
                let _ = eval_expr(stmt, &mut env, state, &state.caps).await?;
            }
            "rst.ok" => {
                let value = eval_expr(
                    stmt.get("v").unwrap_or(&Value::Null),
                    &mut env,
                    state,
                    &state.caps,
                )
                .await?;
                return Ok((StatusCode::OK, json!({"ok": true, "data": value})));
            }
            "rst.err" => {
                let value = eval_expr(
                    stmt.get("v").unwrap_or(&Value::Null),
                    &mut env,
                    state,
                    &state.caps,
                )
                .await?;
                let err_payload = normalize_err_value(&value);
                let code = err_payload
                    .get("code")
                    .and_then(Value::as_str)
                    .unwrap_or("BAD_REQUEST");
                return Ok((
                    status_for_code(code),
                    json!({"ok": false, "error": err_payload}),
                ));
            }
            _ => {
                return Err(RtError::new(
                    "IR_INVALID",
                    format!("unsupported stmt kind '{kind}'"),
                    StatusCode::INTERNAL_SERVER_ERROR,
                ));
            }
        }
    }

    Err(RtError::new(
        "INTERNAL_ERROR",
        "route did not produce response",
        StatusCode::INTERNAL_SERVER_ERROR,
    ))
}

fn ensure_caps(
    granted: &HashSet<String>,
    required: &HashSet<String>,
) -> std::result::Result<(), RtError> {
    for cap in required {
        if !has_cap(granted, cap) {
            return Err(RtError::new(
                "NVR200",
                format!("cap: {cap} required"),
                StatusCode::FORBIDDEN,
            ));
        }
    }
    Ok(())
}

fn has_cap(granted: &HashSet<String>, cap: &str) -> bool {
    if granted.contains(cap) {
        return true;
    }
    cap == "html" && granted.contains("net")
}

fn required_caps_from_body(body: &[Value]) -> HashSet<String> {
    let mut caps = HashSet::new();
    for stmt in body {
        collect_caps(stmt, &mut caps);
    }
    caps
}

fn collect_caps(value: &Value, caps: &mut HashSet<String>) {
    match value {
        Value::Object(obj) => {
            if obj.get("k").and_then(Value::as_str) == Some("cap") {
                if let Some(items) = obj.get("c").and_then(Value::as_array) {
                    for item in items {
                        if let Some(name) = item.as_str() {
                            caps.insert(name.to_lowercase());
                        }
                    }
                }
            }

            if obj.get("k").and_then(Value::as_str) == Some("call") {
                if let Some(fn_name) = obj.get("fn").and_then(Value::as_str) {
                    if let Some(cap) = cap_for_fn(fn_name) {
                        caps.insert(cap.to_string());
                    }
                }
            }

            for val in obj.values() {
                collect_caps(val, caps);
            }
        }
        Value::Array(items) => {
            for item in items {
                collect_caps(item, caps);
            }
        }
        _ => {}
    }
}

fn cap_for_fn(name: &str) -> Option<&'static str> {
    if name.starts_with("http.") || name.starts_with("net.") || name.starts_with("html.") {
        return Some("net");
    }
    if name.starts_with("db.") {
        return Some("db");
    }
    if name.starts_with("fs.") {
        return Some("fs");
    }
    if name.starts_with("env.") {
        return Some("env");
    }
    None
}

#[async_recursion]
async fn eval_expr(
    expr: &Value,
    env: &mut Map<String, Value>,
    state: &AppState,
    caps: &HashSet<String>,
) -> std::result::Result<Value, RtError> {
    let obj = expr.as_object().ok_or_else(|| {
        RtError::new(
            "IR_INVALID",
            "expression must be object",
            StatusCode::INTERNAL_SERVER_ERROR,
        )
    })?;

    let kind = obj.get("k").and_then(Value::as_str).unwrap_or_default();
    match kind {
        "json" => Ok(obj.get("v").cloned().unwrap_or(Value::Null)),
        "id" => {
            let name = obj.get("n").and_then(Value::as_str).ok_or_else(|| {
                RtError::new(
                    "IR_INVALID",
                    "id missing n",
                    StatusCode::INTERNAL_SERVER_ERROR,
                )
            })?;
            Ok(resolve_id(name, env))
        }
        "obj" => {
            let mut out = Map::new();
            if let Some(fields) = obj.get("f").and_then(Value::as_object) {
                for (key, value) in fields {
                    out.insert(key.to_string(), eval_expr(value, env, state, caps).await?);
                }
            }
            Ok(Value::Object(out))
        }
        "arr" => {
            let mut out = Vec::new();
            if let Some(items) = obj.get("i").and_then(Value::as_array) {
                for item in items {
                    out.push(eval_expr(item, env, state, caps).await?);
                }
            }
            Ok(Value::Array(out))
        }
        "call" => {
            let fn_name = obj.get("fn").and_then(Value::as_str).ok_or_else(|| {
                RtError::new(
                    "IR_INVALID",
                    "call missing fn",
                    StatusCode::INTERNAL_SERVER_ERROR,
                )
            })?;
            let mut args = Vec::new();
            if let Some(items) = obj.get("a").and_then(Value::as_array) {
                for item in items {
                    args.push(eval_expr(item, env, state, caps).await?);
                }
            }
            eval_call(fn_name, args, state, caps).await
        }
        other => Err(RtError::new(
            "IR_INVALID",
            format!("unsupported expr kind '{other}'"),
            StatusCode::INTERNAL_SERVER_ERROR,
        )),
    }
}

async fn eval_call(
    fn_name: &str,
    args: Vec<Value>,
    state: &AppState,
    caps: &HashSet<String>,
) -> std::result::Result<Value, RtError> {
    if fn_name == "print" {
        let value = args.first().cloned().unwrap_or(Value::Null);
        println!(
            "{}",
            serde_json::to_string(&value).unwrap_or_else(|_| "null".to_string())
        );
        return Ok(value);
    }

    if fn_name == "to_str" {
        let value = args.first().cloned().unwrap_or(Value::Null);
        let out = if let Some(text) = value.as_str() {
            text.to_string()
        } else {
            value.to_string()
        };
        return Ok(Value::String(out));
    }

    if fn_name == "to_num" {
        let value = args.first().cloned().unwrap_or(Value::Null);
        if let Some(n) = value.as_i64() {
            return Ok(json!(n));
        }
        if let Some(n) = value.as_f64() {
            return Ok(json!(n));
        }
        if let Some(text) = value.as_str() {
            if let Ok(n) = text.parse::<i64>() {
                return Ok(json!(n));
            }
            if let Ok(n) = text.parse::<f64>() {
                return Ok(json!(n));
            }
        }
        return Err(RtError::new(
            "BAD_REQUEST",
            "to_num invalid value",
            StatusCode::BAD_REQUEST,
        ));
    }

    if fn_name == "http.get" || fn_name == "net.get" {
        require_cap(caps, "net")?;
        return http_get(args).await;
    }

    if fn_name == "html.tte" {
        require_cap(caps, "net")?;
        return Ok(Value::String(html_tte(
            args.first().cloned().unwrap_or(Value::Null),
        )));
    }

    if fn_name == "html.sct" {
        require_cap(caps, "net")?;
        let html_value = args.first().cloned().unwrap_or(Value::Null);
        let selector = args.get(1).and_then(Value::as_str).unwrap_or("");
        let values = html_sct(html_value, selector)?;
        return Ok(Value::Array(
            values.into_iter().map(Value::String).collect(),
        ));
    }

    if fn_name == "db.opn" {
        require_cap(caps, "db")?;
        let path = args.first().and_then(Value::as_str).ok_or_else(|| {
            RtError::new("DB_INPUT", "db.opn requires path", StatusCode::BAD_REQUEST)
        })?;
        let handle = db_opn(state, path).await?;
        return Ok(json!(handle));
    }

    if fn_name == "db.qry" {
        require_cap(caps, "db")?;
        let handle = args.first().ok_or_else(|| {
            RtError::new(
                "DB_INPUT",
                "db.qry requires handle",
                StatusCode::BAD_REQUEST,
            )
        })?;
        let sql = args.get(1).and_then(Value::as_str).ok_or_else(|| {
            RtError::new("DB_INPUT", "db.qry requires sql", StatusCode::BAD_REQUEST)
        })?;
        let params = args.get(2).cloned();
        return db_qry(state, handle, sql, params).await;
    }

    if fn_name == "db.cls" {
        require_cap(caps, "db")?;
        let handle = args.first().ok_or_else(|| {
            RtError::new(
                "DB_INPUT",
                "db.cls requires handle",
                StatusCode::BAD_REQUEST,
            )
        })?;
        db_cls(state, handle).await?;
        return Ok(Value::Bool(true));
    }

    if fn_name == "env.get" {
        require_cap(caps, "env")?;
        let key = args.first().and_then(Value::as_str).ok_or_else(|| {
            RtError::new(
                "BAD_REQUEST",
                "env.get requires key",
                StatusCode::BAD_REQUEST,
            )
        })?;
        let default = args.get(1).cloned().unwrap_or(Value::Null);
        let value = env::var(key).map(Value::String).unwrap_or(default);
        return Ok(value);
    }

    if fn_name == "env.keys" {
        require_cap(caps, "env")?;
        let mut keys: Vec<String> = env::vars().map(|(k, _)| k).collect();
        keys.sort();
        return Ok(Value::Array(keys.into_iter().map(Value::String).collect()));
    }

    if fn_name == "fs.read" {
        require_cap(caps, "fs")?;
        let path = args.first().and_then(Value::as_str).ok_or_else(|| {
            RtError::new(
                "BAD_REQUEST",
                "fs.read requires path",
                StatusCode::BAD_REQUEST,
            )
        })?;
        let target = resolve_under_root(state.root.as_ref(), path);
        let text = fs::read_to_string(&target)
            .with_context(|| format!("fs.read failed for {}", target.display()))
            .map_err(|exc| RtError::new("FS_READ", exc.to_string(), StatusCode::BAD_REQUEST))?;
        return Ok(Value::String(text));
    }

    if fn_name == "fs.exists" {
        require_cap(caps, "fs")?;
        let path = args.first().and_then(Value::as_str).ok_or_else(|| {
            RtError::new(
                "BAD_REQUEST",
                "fs.exists requires path",
                StatusCode::BAD_REQUEST,
            )
        })?;
        let target = resolve_under_root(state.root.as_ref(), path);
        return Ok(Value::Bool(target.exists()));
    }

    if fn_name == "fs.write" {
        require_cap(caps, "fs")?;
        let path = args.first().and_then(Value::as_str).ok_or_else(|| {
            RtError::new(
                "BAD_REQUEST",
                "fs.write requires path",
                StatusCode::BAD_REQUEST,
            )
        })?;
        let content = args.get(1).map(value_to_string).ok_or_else(|| {
            RtError::new(
                "BAD_REQUEST",
                "fs.write requires content",
                StatusCode::BAD_REQUEST,
            )
        })?;
        let target = resolve_under_root(state.root.as_ref(), path);
        if let Some(parent) = target.parent() {
            fs::create_dir_all(parent).map_err(|exc| {
                RtError::new("FS_WRITE", exc.to_string(), StatusCode::BAD_REQUEST)
            })?;
        }
        fs::write(&target, content.as_bytes())
            .map_err(|exc| RtError::new("FS_WRITE", exc.to_string(), StatusCode::BAD_REQUEST))?;
        return Ok(json!({"p": target.to_string_lossy(), "n": content.len()}));
    }

    Err(RtError::new(
        "BAD_REQUEST",
        format!("unsupported call '{fn_name}'"),
        StatusCode::BAD_REQUEST,
    ))
}

fn require_cap(caps: &HashSet<String>, cap: &str) -> std::result::Result<(), RtError> {
    if has_cap(caps, cap) {
        return Ok(());
    }
    Err(RtError::new(
        "NVR200",
        format!("cap: {cap} required"),
        StatusCode::FORBIDDEN,
    ))
}

async fn http_get(args: Vec<Value>) -> std::result::Result<Value, RtError> {
    let url = args.first().and_then(Value::as_str).ok_or_else(|| {
        RtError::new(
            "NET_INPUT",
            "http.get requires url",
            StatusCode::BAD_REQUEST,
        )
    })?;

    let timeout = args
        .get(2)
        .and_then(Value::as_f64)
        .or_else(|| args.get(2).and_then(Value::as_i64).map(|v| v as f64))
        .unwrap_or(8.0);
    if timeout <= 0.0 {
        return Err(RtError::new(
            "NET_INPUT",
            "http.get timeout must be > 0",
            StatusCode::BAD_REQUEST,
        ));
    }

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs_f64(timeout))
        .build()
        .map_err(|exc| RtError::new("NET_REQ", exc.to_string(), StatusCode::BAD_GATEWAY))?;

    let mut req = client.get(url);
    if let Some(headers) = args.get(1).and_then(Value::as_object) {
        for (key, value) in headers {
            let Ok(name) = HeaderName::from_bytes(key.as_bytes()) else {
                continue;
            };
            let Ok(header_val) = HeaderValue::from_str(&value_to_string(value)) else {
                continue;
            };
            req = req.header(name, header_val);
        }
    }

    let res = req
        .send()
        .await
        .map_err(|exc| RtError::new("NET_REQ", exc.to_string(), StatusCode::BAD_GATEWAY))?;
    let status = res.status().as_u16();
    let mut hd = Map::new();
    for (key, value) in res.headers() {
        if let Ok(text) = value.to_str() {
            hd.insert(key.to_string(), Value::String(text.to_string()));
        }
    }
    let body = res
        .text()
        .await
        .map_err(|exc| RtError::new("NET_REQ", exc.to_string(), StatusCode::BAD_GATEWAY))?;

    Ok(json!({"st": status, "hd": hd, "bd": body}))
}

fn html_tte(value: Value) -> String {
    let html = html_source(value);
    let doc = Html::parse_document(&html);
    let Ok(selector) = Selector::parse("title") else {
        return String::new();
    };
    if let Some(node) = doc.select(&selector).next() {
        return node.text().collect::<Vec<_>>().join(" ").trim().to_string();
    }
    String::new()
}

fn html_sct(value: Value, selector: &str) -> std::result::Result<Vec<String>, RtError> {
    let css = selector.trim();
    if css.is_empty() {
        return Ok(Vec::new());
    }
    let sel = Selector::parse(css).map_err(|exc| {
        RtError::new(
            "BAD_REQUEST",
            format!("invalid selector: {exc}"),
            StatusCode::BAD_REQUEST,
        )
    })?;
    let html = html_source(value);
    let doc = Html::parse_document(&html);
    let mut out = Vec::new();
    for node in doc.select(&sel) {
        out.push(node.text().collect::<Vec<_>>().join(" ").trim().to_string());
    }
    Ok(out)
}

fn html_source(value: Value) -> String {
    if let Some(text) = value.as_str() {
        return text.to_string();
    }
    if let Some(obj) = value.as_object() {
        if let Some(text) = obj.get("bd").and_then(Value::as_str) {
            return text.to_string();
        }
    }
    value_to_string(&value)
}

async fn db_opn(state: &AppState, raw_path: &str) -> std::result::Result<u64, RtError> {
    let target = resolve_under_root(state.root.as_ref(), raw_path);
    if let Some(parent) = target.parent() {
        fs::create_dir_all(parent)
            .map_err(|exc| RtError::new("DB_OPEN", exc.to_string(), StatusCode::BAD_REQUEST))?;
    }
    Connection::open(&target)
        .map_err(|exc| RtError::new("DB_OPEN", exc.to_string(), StatusCode::BAD_REQUEST))?;

    let mut db = state.db.lock().await;
    db.seq += 1;
    let handle = db.seq;
    db.handles.insert(handle, target);
    Ok(handle)
}

async fn db_cls(state: &AppState, handle: &Value) -> std::result::Result<(), RtError> {
    let id = value_to_u64(handle).ok_or_else(|| {
        RtError::new(
            "DB_INPUT",
            "db.cls requires numeric handle",
            StatusCode::BAD_REQUEST,
        )
    })?;
    let mut db = state.db.lock().await;
    if db.handles.remove(&id).is_none() {
        return Err(RtError::new(
            "DB_HANDLE",
            format!("unknown db handle '{id}'"),
            StatusCode::BAD_REQUEST,
        ));
    }
    Ok(())
}

async fn db_qry(
    state: &AppState,
    handle: &Value,
    sql: &str,
    args: Option<Value>,
) -> std::result::Result<Value, RtError> {
    let id = value_to_u64(handle).ok_or_else(|| {
        RtError::new(
            "DB_INPUT",
            "db.qry requires numeric handle",
            StatusCode::BAD_REQUEST,
        )
    })?;
    let path = {
        let db = state.db.lock().await;
        db.handles.get(&id).cloned().ok_or_else(|| {
            RtError::new(
                "DB_HANDLE",
                format!("unknown db handle '{id}'"),
                StatusCode::BAD_REQUEST,
            )
        })?
    };

    let conn = Connection::open(path)
        .map_err(|exc| RtError::new("DB_OPEN", exc.to_string(), StatusCode::BAD_REQUEST))?;
    let mut stmt = conn
        .prepare(sql)
        .map_err(|exc| RtError::new("DB_QRY", exc.to_string(), StatusCode::BAD_REQUEST))?;

    let bind_values = normalize_sql_args(args)?;
    if stmt.column_count() == 0 {
        let cnt = stmt
            .execute(params_from_iter(bind_values))
            .map_err(|exc| RtError::new("DB_QRY", exc.to_string(), StatusCode::BAD_REQUEST))?;
        return Ok(json!({"cnt": cnt}));
    }

    let col_names: Vec<String> = stmt
        .column_names()
        .iter()
        .map(|name| name.to_string())
        .collect();
    let mut rows = stmt
        .query(params_from_iter(bind_values))
        .map_err(|exc| RtError::new("DB_QRY", exc.to_string(), StatusCode::BAD_REQUEST))?;

    let mut out = Vec::new();
    while let Some(row) = rows
        .next()
        .map_err(|exc| RtError::new("DB_QRY", exc.to_string(), StatusCode::BAD_REQUEST))?
    {
        let mut item = Map::new();
        for (idx, name) in col_names.iter().enumerate() {
            let value_ref = row
                .get_ref(idx)
                .map_err(|exc| RtError::new("DB_QRY", exc.to_string(), StatusCode::BAD_REQUEST))?;
            item.insert(name.clone(), sql_ref_to_json(value_ref));
        }
        out.push(Value::Object(item));
    }

    Ok(Value::Array(out))
}

fn normalize_sql_args(args: Option<Value>) -> std::result::Result<Vec<SqlValue>, RtError> {
    let Some(value) = args else {
        return Ok(Vec::new());
    };
    match value {
        Value::Null => Ok(Vec::new()),
        Value::Array(items) => Ok(items.into_iter().map(json_to_sql_value).collect()),
        _ => Err(RtError::new(
            "DB_INPUT",
            "db.qry args must be list",
            StatusCode::BAD_REQUEST,
        )),
    }
}

fn json_to_sql_value(value: Value) -> SqlValue {
    match value {
        Value::Null => SqlValue::Null,
        Value::Bool(v) => SqlValue::Integer(if v { 1 } else { 0 }),
        Value::Number(v) => {
            if let Some(i) = v.as_i64() {
                SqlValue::Integer(i)
            } else if let Some(f) = v.as_f64() {
                SqlValue::Real(f)
            } else {
                SqlValue::Null
            }
        }
        Value::String(v) => SqlValue::Text(v),
        other => SqlValue::Text(other.to_string()),
    }
}

fn sql_ref_to_json(value: ValueRef<'_>) -> Value {
    match value {
        ValueRef::Null => Value::Null,
        ValueRef::Integer(v) => json!(v),
        ValueRef::Real(v) => json!(v),
        ValueRef::Text(v) => Value::String(String::from_utf8_lossy(v).to_string()),
        ValueRef::Blob(v) => Value::String(format!("<blob:{}>", v.len())),
    }
}

fn normalize_path(path: &str) -> String {
    if path.is_empty() {
        return "/".to_string();
    }
    let mut out = path.trim().to_string();
    if !out.starts_with('/') {
        out = format!("/{out}");
    }
    if out.len() > 1 && out.ends_with('/') {
        out.pop();
    }
    out
}

fn normalize_method(method: &str) -> String {
    let raw = method.to_uppercase();
    match raw.as_str() {
        "DEL" => "DELETE".to_string(),
        "PAT" => "PATCH".to_string(),
        "OPT" => "OPTIONS".to_string(),
        "HED" => "HEAD".to_string(),
        _ => raw,
    }
}

fn match_route_path(pattern: &str, path: &str) -> Option<Map<String, Value>> {
    let expected = normalize_path(pattern);
    let got = normalize_path(path);
    let expected_parts: Vec<&str> = expected
        .split('/')
        .filter(|item| !item.is_empty())
        .collect();
    let got_parts: Vec<&str> = got.split('/').filter(|item| !item.is_empty()).collect();

    if expected_parts.len() != got_parts.len() {
        if expected == "/" && got == "/" {
            return Some(Map::new());
        }
        return None;
    }

    let mut params = Map::new();
    for (left, right) in expected_parts.iter().zip(got_parts.iter()) {
        if left.starts_with(':') && left.len() > 1 {
            params.insert(left[1..].to_string(), Value::String((*right).to_string()));
            continue;
        }
        if left != right {
            return None;
        }
    }
    Some(params)
}

fn parse_query(raw: &str) -> Map<String, Value> {
    let mut out = Map::new();
    for (key, value) in form_urlencoded::parse(raw.as_bytes()) {
        let key_s = key.to_string();
        let val = Value::String(value.to_string());
        if let Some(prev) = out.get_mut(&key_s) {
            match prev {
                Value::Array(items) => items.push(val),
                other => {
                    let first = other.clone();
                    *other = Value::Array(vec![first, val]);
                }
            }
        } else {
            out.insert(key_s, val);
        }
    }
    out
}

fn parse_headers(headers: &HeaderMap) -> Map<String, Value> {
    let mut out = Map::new();
    for (key, value) in headers {
        if let Ok(text) = value.to_str() {
            out.insert(key.to_string(), Value::String(text.to_string()));
        }
    }
    out
}

fn resolve_id(name: &str, env: &Map<String, Value>) -> Value {
    if name == "tru" {
        return Value::Bool(true);
    }
    if name == "fal" {
        return Value::Bool(false);
    }
    if name == "nul" {
        return Value::Null;
    }

    let mut parts = name.split('.');
    let Some(first) = parts.next() else {
        return Value::Null;
    };
    let Some(mut current) = env.get(first).cloned() else {
        return Value::Null;
    };

    for part in parts {
        match current {
            Value::Object(map) => {
                current = map.get(part).cloned().unwrap_or(Value::Null);
            }
            Value::Array(items) => {
                if let Ok(index) = part.parse::<usize>() {
                    current = items.get(index).cloned().unwrap_or(Value::Null);
                } else {
                    return Value::Null;
                }
            }
            _ => return Value::Null,
        }
    }
    current
}

fn normalize_err_value(value: &Value) -> Value {
    if let Some(obj) = value.as_object() {
        let code = obj
            .get("code")
            .and_then(Value::as_str)
            .unwrap_or("BAD_REQUEST")
            .to_string();
        let msg = obj
            .get("msg")
            .and_then(Value::as_str)
            .unwrap_or("error")
            .to_string();
        let mut out = Map::new();
        out.insert("code".to_string(), Value::String(code));
        out.insert("msg".to_string(), Value::String(msg));
        if let Some(details) = obj.get("details") {
            out.insert("details".to_string(), details.clone());
        }
        return Value::Object(out);
    }
    json!({"code": "BAD_REQUEST", "msg": value_to_string(value)})
}

fn status_for_code(code: &str) -> StatusCode {
    match code {
        "BAD_REQUEST" | "INVALID_INPUT" | "DB_INPUT" | "DB_HANDLE" | "NET_INPUT" => {
            StatusCode::BAD_REQUEST
        }
        "UNAUTHORIZED" => StatusCode::UNAUTHORIZED,
        "FORBIDDEN" | "CAP_FORBIDDEN" | "CAP_DECLARATION_REQUIRED" | "NVR200" => {
            StatusCode::FORBIDDEN
        }
        "NOT_FOUND" | "ROUTE_NOT_FOUND" => StatusCode::NOT_FOUND,
        "METHOD_NOT_ALLOWED" => StatusCode::METHOD_NOT_ALLOWED,
        "CONFLICT" => StatusCode::CONFLICT,
        "UNPROCESSABLE" => StatusCode::UNPROCESSABLE_ENTITY,
        "TOO_MANY_REQUESTS" => StatusCode::TOO_MANY_REQUESTS,
        "NOT_IMPLEMENTED" => StatusCode::NOT_IMPLEMENTED,
        "NET_REQ" => StatusCode::BAD_GATEWAY,
        _ => StatusCode::INTERNAL_SERVER_ERROR,
    }
}

fn value_to_u64(value: &Value) -> Option<u64> {
    if let Some(v) = value.as_u64() {
        return Some(v);
    }
    if let Some(v) = value.as_i64() {
        if v >= 0 {
            return Some(v as u64);
        }
    }
    if let Some(v) = value.as_str() {
        return v.parse::<u64>().ok();
    }
    None
}

fn value_to_string(value: &Value) -> String {
    if let Some(text) = value.as_str() {
        text.to_string()
    } else {
        value.to_string()
    }
}

fn resolve_under_root(root: &Path, raw: &str) -> PathBuf {
    let path = PathBuf::from(raw);
    if path.is_absolute() {
        path
    } else {
        root.join(path)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn html_helpers_work() {
        let html = "<html><head><title>Demo</title></head><body><h1>A</h1><h1>B</h1></body></html>";
        let title = html_tte(Value::String(html.to_string()));
        assert_eq!(title, "Demo");
        let list = html_sct(Value::String(html.to_string()), "h1").expect("selector");
        assert_eq!(list, vec!["A".to_string(), "B".to_string()]);
    }

    #[test]
    fn cap_guard_blocks_missing_cap() {
        let granted: HashSet<String> = HashSet::new();
        let required = HashSet::from([String::from("net")]);
        let err = ensure_caps(&granted, &required).expect_err("must fail");
        assert_eq!(err.code, "NVR200");
        assert_eq!(err.status, StatusCode::FORBIDDEN);
    }
}
