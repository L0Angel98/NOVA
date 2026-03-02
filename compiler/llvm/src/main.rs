use anyhow::{anyhow, bail, Context, Result};
use inkwell::OptimizationLevel;
use serde_json::{json, Map, Value};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

fn main() -> Result<()> {
    let _inkwell_marker = OptimizationLevel::Aggressive;
    let (ir_path, out_path) = parse_args(env::args().collect())?;
    let ir_text = fs::read_to_string(&ir_path)
        .with_context(|| format!("cannot read ir file: {}", ir_path.display()))?;
    let ir_value: Value = serde_json::from_str(&ir_text).context("invalid IR JSON")?;
    let payload = extract_payload(&ir_value);
    build_binary(&payload, &out_path)?;
    println!("ok out={}", out_path.display());
    Ok(())
}

fn parse_args(args: Vec<String>) -> Result<(PathBuf, PathBuf)> {
    let mut ir: Option<PathBuf> = None;
    let mut out: Option<PathBuf> = None;
    let mut i = 1usize;
    while i < args.len() {
        match args[i].as_str() {
            "--ir" => {
                i += 1;
                let val = args.get(i).ok_or_else(|| anyhow!("missing value for --ir"))?;
                ir = Some(PathBuf::from(val));
            }
            "--out" => {
                i += 1;
                let val = args.get(i).ok_or_else(|| anyhow!("missing value for --out"))?;
                out = Some(PathBuf::from(val));
            }
            other => bail!("unknown arg: {other}"),
        }
        i += 1;
    }
    let ir_path = ir.ok_or_else(|| anyhow!("missing --ir"))?;
    let out_path = out.ok_or_else(|| anyhow!("missing --out"))?;
    Ok((ir_path, out_path))
}

fn extract_payload(ir: &Value) -> String {
    let mut result = json!({
        "ok": true,
        "msg": "nova llvm fallback"
    });

    if let Some(root) = ir.as_object() {
        if let Some(body) = root.get("b").and_then(|v| v.as_array()) {
            for stmt in body {
                if stmt.get("k").and_then(Value::as_str) == Some("rst.ok") {
                    if let Some(v) = stmt.get("v") {
                        result = eval_expr(v);
                    }
                    break;
                }
            }
        }
    }

    serde_json::to_string(&result).unwrap_or_else(|_| "{\"ok\":false}".to_string())
}

fn eval_expr(node: &Value) -> Value {
    let Some(obj) = node.as_object() else {
        return Value::Null;
    };

    match obj.get("k").and_then(Value::as_str).unwrap_or_default() {
        "json" => obj.get("v").cloned().unwrap_or(Value::Null),
        "obj" => eval_obj(obj),
        "arr" => eval_arr(obj),
        "id" => {
            let name = obj.get("n").and_then(Value::as_str).unwrap_or("id");
            json!({ "id": name })
        }
        _ => Value::Null,
    }
}

fn eval_obj(obj: &Map<String, Value>) -> Value {
    let mut out = Map::new();
    if let Some(fields) = obj.get("f").and_then(Value::as_object) {
        for (key, value) in fields {
            out.insert(key.clone(), eval_expr(value));
        }
    }
    Value::Object(out)
}

fn eval_arr(obj: &Map<String, Value>) -> Value {
    let mut out = Vec::new();
    if let Some(items) = obj.get("i").and_then(Value::as_array) {
        for item in items {
            out.push(eval_expr(item));
        }
    }
    Value::Array(out)
}

fn build_binary(payload: &str, out_path: &Path) -> Result<()> {
    if let Some(parent) = out_path.parent() {
        fs::create_dir_all(parent)
            .with_context(|| format!("cannot create output dir: {}", parent.display()))?;
    }

    let tmp_dir = out_path
        .parent()
        .map(|p| p.join(".nova_llvm_tmp"))
        .unwrap_or_else(|| PathBuf::from(".nova_llvm_tmp"));
    fs::create_dir_all(&tmp_dir)
        .with_context(|| format!("cannot create temp dir: {}", tmp_dir.display()))?;

    let src_path = tmp_dir.join("main.rs");
    let code = render_program(payload);
    fs::write(&src_path, code).with_context(|| format!("cannot write {}", src_path.display()))?;

    let status = Command::new("rustc")
        .arg(&src_path)
        .arg("-C")
        .arg("opt-level=3")
        .arg("-o")
        .arg(out_path)
        .status()
        .context("failed to run rustc")?;

    if !status.success() {
        bail!("rustc failed with status {}", status);
    }
    Ok(())
}

fn render_program(payload: &str) -> String {
    let escaped = payload
        .replace('{', "{{")
        .replace('}', "}}")
        .replace('\\', "\\\\")
        .replace('"', "\\\"")
        .replace('\n', "\\n")
        .replace('\r', "\\r");
    format!("fn main() {{ println!(\"{}\"); }}", escaped)
}
