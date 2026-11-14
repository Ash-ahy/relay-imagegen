#!/usr/bin/env python3
"""Configure or check relay-imagegen private config files."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import sqlite3
import sys
import threading
from typing import Any
from urllib.parse import urlsplit, urlunsplit


SKILL_DIR = Path(__file__).resolve().parents[1]
ROOT_CONFIG = SKILL_DIR / "config.json"
SKILL_CONFIG = SKILL_DIR / ".secrets" / "config.json"
CCSWITCH_DB = Path.home() / ".cc-switch" / "cc-switch.db"
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
CODEX_CONFIG = CODEX_HOME / "config.toml"
CODEX_AUTH = CODEX_HOME / "auth.json"
DEFAULT_MODEL = "gpt-image-2.5-flare"
MODEL_PRESETS = {
    "Flare（推荐）": "gpt-image-2.5-flare",
    "Sunburst": "gpt-image-2.5-sunburst",
    "Image 2（兼容）": "gpt-image-2",
}


def user_config_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "relay-imagegen" / "config.json"
    return Path.home() / ".config" / "relay-imagegen" / "config.json"


def candidate_paths(include_skill_config: bool = True) -> list[Path]:
    paths = []
    env_path = os.environ.get("RELAY_IMAGEGEN_CONFIG")
    paths.append(ROOT_CONFIG)
    if env_path:
        paths.append(Path(env_path))
    paths.extend(
        [
            Path.cwd() / "photo" / "api_key.json",
            Path.cwd() / ".secrets" / "image_api.json",
            Path.cwd() / ".secrets" / "relay_imagegen.json",
            SKILL_CONFIG if include_skill_config else None,
            user_config_path(),
            Path.home() / ".config" / "relay-imagegen" / "config.json",
            Path.home() / ".relay-imagegen.json",
        ]
    )
    deduped = []
    seen = set()
    for path in paths:
        if path is None:
            continue
        key = str(path).lower()
        if key not in seen:
            deduped.append(path)
            seen.add(key)
    return deduped


def load_json(path: Path, quiet: bool = False) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        if not quiet:
            print(f"BROKEN_CONFIG={path} ({exc})")
        return None


def check_json_config(path: Path, quiet: bool = False) -> int:
    data = load_json(path, quiet=quiet)
    if data is None:
        return 1
    sources = data.get("sources") if isinstance(data.get("sources"), list) else None
    first = sources[0] if sources and isinstance(sources[0], dict) else data
    api_key = (
        first.get("api_key")
        or first.get("apiKey")
        or first.get("key")
        or first.get("token")
        or first.get("openai_api_key")
        or first.get("OPENAI_API_KEY")
        or data.get("api_key")
        or data.get("apiKey")
        or data.get("key")
        or data.get("token")
        or data.get("openai_api_key")
        or data.get("OPENAI_API_KEY")
    )
    base_url = (
        first.get("base_url")
        or first.get("baseUrl")
        or first.get("baseURL")
        or first.get("api_base")
        or first.get("endpoint")
        or first.get("openai_base_url")
        or first.get("OPENAI_BASE_URL")
        or data.get("base_url")
        or data.get("baseUrl")
        or data.get("baseURL")
        or data.get("api_base")
        or data.get("endpoint")
        or data.get("openai_base_url")
        or data.get("OPENAI_BASE_URL")
    )
    model = first.get("model") or data.get("model", DEFAULT_MODEL)
    if quiet:
        return 0 if api_key and base_url and (not sources or all(isinstance(item, dict) and item.get("api_key") and item.get("base_url") for item in sources)) else 2
    print(f"CONFIG={path}")
    if sources:
        print(f"SOURCES={len(sources)}")
    print(f"API_KEY={redact(str(api_key)) if api_key else 'missing'}")
    print(f"BASE_URL={base_url or 'missing'}")
    print(f"MODEL={model}")
    return 0 if api_key and base_url and (not sources or all(isinstance(item, dict) and item.get("api_key") and item.get("base_url") for item in sources)) else 2


def redact(value: str | None) -> str:
    if not value:
        return ""
    return value[:4] + "..." + value[-4:] if len(value) > 10 else "***"


def normalize_openai_base_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme and parsed.netloc and parsed.path in {"", "/"}:
        return urlunsplit((parsed.scheme, parsed.netloc, "/v1", parsed.query, parsed.fragment))
    return url


class ModelDiscoveryError(ValueError):
    """A fixed, credential-free message suitable for the configuration UI."""


def fetch_upstream_models(base_url: str, api_key: str) -> list[str]:
    """Read the relay catalogue without issuing an image request or logging secrets."""
    from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

    try:
        parsed = urlsplit(base_url.strip())
        valid_url = parsed.scheme in {"https", "http"} and bool(parsed.hostname) and not parsed.username and not parsed.password
        if parsed.port is not None:
            valid_url = valid_url and 0 < parsed.port < 65536
    except ValueError:
        valid_url = False
    if not valid_url:
        raise ModelDiscoveryError("请填写有效的中转站地址。")
    if not api_key.strip():
        raise ModelDiscoveryError("请先填写访问密钥。")
    try:
        with OpenAI(api_key=api_key.strip(), base_url=normalize_openai_base_url(base_url.strip()), timeout=15.0, max_retries=0) as client:
            response = client.models.list()
            items = response.data
            if not isinstance(items, list):
                raise ModelDiscoveryError("模型接口返回格式不兼容，可手动填写模型 ID。")
            ids = [item if isinstance(item, str) else item.get("id") if isinstance(item, dict) else getattr(item, "id", None) for item in items]
            return sorted({model.strip() for model in ids if isinstance(model, str) and model.strip()})
    except APITimeoutError:
        raise ModelDiscoveryError("获取模型超时，请稍后点击刷新。") from None
    except APIConnectionError:
        raise ModelDiscoveryError("无法连接模型接口，请检查地址或网络。") from None
    except APIStatusError as exc:
        messages = {401: "密钥无效或已过期", 403: "当前密钥没有读取模型列表的权限", 404: "上游未提供模型列表接口，请手动填写模型 ID", 429: "请求过于频繁，请稍后刷新"}
        raise ModelDiscoveryError(f"获取模型失败（HTTP {exc.status_code}）：{messages.get(exc.status_code, '上游暂时无法返回模型列表')}。") from None
    except ModelDiscoveryError:
        raise
    except Exception:
        raise ModelDiscoveryError("模型接口返回格式不兼容，可手动填写模型 ID。") from None


def likely_image_models(models: list[str]) -> list[str]:
    # A catalogue ID is only a hint; it does not prove Images API compatibility.
    markers = ("image", "dall-e", "flux", "sdxl", "stable-diffusion", "seedream", "imagen", "sunburst", "flare")
    return [model for model in models if any(marker in model.lower() for marker in markers)]


def extract_base_url_from_ccswitch_config(config: Any) -> str | None:
    if isinstance(config, dict):
        for key in ("base_url", "baseUrl", "baseURL", "api_base", "endpoint", "openai_base_url", "OPENAI_BASE_URL"):
            if config.get(key):
                return str(config[key])
        return None
    if not isinstance(config, str):
        return None
    for key in ("base_url", "baseUrl", "baseURL", "api_base", "endpoint", "openai_base_url", "OPENAI_BASE_URL"):
        match = re.search(rf"(?m)^\s*{re.escape(key)}\s*=\s*[\"']([^\"']+)[\"']", config)
        if match:
            return match.group(1)
    return None


def check() -> int:
    if ROOT_CONFIG.exists():
        return check_json_config(ROOT_CONFIG)
    if SKILL_CONFIG.exists():
        skill_status = check_json_config(SKILL_CONFIG, quiet=True)
        if skill_status == 0:
            check_json_config(SKILL_CONFIG)
            return 0

    codex_status = check_codex(quiet_missing=True)
    if codex_status == 0:
        return 0
    ccswitch_status = check_ccswitch(quiet_missing=True)
    if ccswitch_status == 0:
        return 0
    found = False
    for path in candidate_paths(include_skill_config=False):
        if not path.exists():
            continue
        found = True
        status = check_json_config(path)
        if status != 1:
            return status
    if not found:
        print("CONFIG=missing")
        print("If Codex already uses a relay, run: python scripts/setup.py --check-codex")
        print(f"Suggested skill-local path: {SKILL_CONFIG}")
        print(f"Suggested user path: {user_config_path()}")
        print("If you use ccswitch, run: python scripts/setup.py --check-ccswitch")
    return 1


def parse_toml(path: Path) -> dict[str, Any]:
    try:
        import tomllib
    except ModuleNotFoundError:
        tomllib = None
    if tomllib is not None:
        with path.open("rb") as f:
            return tomllib.load(f)
    return parse_codex_toml_fallback(path.read_text(encoding="utf-8"))


def parse_codex_toml_fallback(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    section: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = [part.strip().strip('"').strip("'") for part in line.strip("[]").split(".")]
            current = data
            for part in section:
                current = current.setdefault(part, {})
            continue
        if "=" not in line:
            continue
        key, raw_value = [part.strip() for part in line.split("=", 1)]
        value = raw_value.strip().strip('"').strip("'")
        current = data
        for part in section:
            current = current.setdefault(part, {})
        current[key] = value
    return data


def check_codex(
    config_path: Path = CODEX_CONFIG,
    auth_path: Path = CODEX_AUTH,
    quiet_missing: bool = False,
) -> int:
    if not config_path.exists() or not auth_path.exists():
        if not quiet_missing:
            print(f"CODEX_CONFIG={'missing' if not config_path.exists() else config_path}")
            print(f"CODEX_AUTH={'missing' if not auth_path.exists() else auth_path}")
        return 1
    try:
        config = parse_toml(config_path)
        auth = json.loads(auth_path.read_text(encoding="utf-8"))
    except Exception as exc:
        if not quiet_missing:
            print(f"CODEX_ERROR={exc}")
        return 1
    provider_name = config.get("model_provider")
    providers = config.get("model_providers") if isinstance(config.get("model_providers"), dict) else {}
    provider = providers.get(provider_name) if provider_name else None
    if not isinstance(provider, dict):
        if not quiet_missing:
            print("CODEX_PROVIDER=missing")
        return 1
    api_key = (
        auth.get("api_key")
        or auth.get("apiKey")
        or auth.get("key")
        or auth.get("token")
        or auth.get("openai_api_key")
        or auth.get("OPENAI_API_KEY")
    )
    base_url = (
        provider.get("base_url")
        or provider.get("baseUrl")
        or provider.get("baseURL")
        or provider.get("api_base")
        or provider.get("endpoint")
        or provider.get("openai_base_url")
        or provider.get("OPENAI_BASE_URL")
    )
    image_model = provider.get("image_model") or provider.get("imageModel") or DEFAULT_MODEL
    print(f"CODEX_CONFIG={config_path}")
    print(f"CODEX_AUTH={auth_path}")
    print(f"CODEX_PROVIDER={provider_name}")
    print(f"API_KEY={redact(str(api_key)) if api_key else 'missing'}")
    print(f"BASE_URL={normalize_openai_base_url(str(base_url)) if base_url else 'missing'}")
    print(f"MODEL={image_model}")
    return 0 if api_key and base_url else 2


def check_ccswitch(db_path: Path = CCSWITCH_DB, app_type: str = "codex", quiet_missing: bool = False) -> int:
    if not db_path.exists():
        if not quiet_missing:
            print(f"CCSWITCH_DB=missing ({db_path})")
        return 1
    try:
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        provider = con.execute(
            "select id, name, settings_config from providers where app_type=? and is_current=1 limit 1",
            (app_type,),
        ).fetchone()
        if provider is None:
            if not quiet_missing:
                print(f"CCSWITCH_PROVIDER=missing app_type={app_type}")
            return 1
        settings = json.loads(provider["settings_config"] or "{}")
        auth = settings.get("auth") if isinstance(settings.get("auth"), dict) else {}
        api_key = (
            auth.get("api_key")
            or auth.get("apiKey")
            or auth.get("key")
            or auth.get("token")
            or auth.get("openai_api_key")
            or auth.get("OPENAI_API_KEY")
        )
        endpoint = con.execute(
            "select url from provider_endpoints where app_type=? and provider_id=? order by id asc limit 1",
            (app_type, provider["id"]),
        ).fetchone()
    except sqlite3.Error as exc:
        if not quiet_missing:
            print(f"CCSWITCH_ERROR={exc}")
        return 1
    except json.JSONDecodeError as exc:
        if not quiet_missing:
            print(f"CCSWITCH_SETTINGS_ERROR={exc}")
        return 1
    finally:
        try:
            con.close()
        except Exception:
            pass
    print(f"CCSWITCH_DB={db_path}")
    print(f"CCSWITCH_PROVIDER={provider['name']} ({provider['id']})")
    print(f"API_KEY={redact(str(api_key)) if api_key else 'missing'}")
    base_url = extract_base_url_from_ccswitch_config(settings.get("config"))
    if not base_url and endpoint:
        base_url = endpoint["url"]
    print(f"BASE_URL={normalize_openai_base_url(base_url) if base_url else 'missing'}")
    print(f"MODEL={DEFAULT_MODEL}")
    return 0 if api_key and base_url else 2


def write_config(path: Path, overwrite: bool) -> int:
    if path.exists() and not overwrite:
        print(f"Config already exists: {path}")
        print("Use --force to overwrite it.")
        return 2
    print(f"Writing private relay config to: {path}")
    base_url = input("Relay base_url: ").strip()
    model = input(f"Model [{DEFAULT_MODEL}]: ").strip() or DEFAULT_MODEL
    api_key = getpass.getpass("API key (hidden): ").strip()
    if not api_key or not base_url:
        print("api_key and base_url are required.", file=sys.stderr)
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"api_key": api_key, "base_url": base_url, "model": model}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("WROTE_CONFIG=1")
    print(f"CONFIG={path}")
    return 0


def open_advanced_gui() -> int:
    """Open the full multi-source configuration window."""
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ImportError:
        print("Tkinter is not available in this Python installation.", file=sys.stderr)
        return 1

    loaded_config = load_json(ROOT_CONFIG, quiet=True)
    existing = loaded_config if isinstance(loaded_config, dict) else {}
    raw_sources = existing.get("sources") if isinstance(existing.get("sources"), list) else [existing]
    sources: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_sources):
        if not isinstance(raw, dict):
            continue
        api_key = raw.get("api_key") or raw.get("apiKey") or raw.get("key") or ""
        base_url = raw.get("base_url") or raw.get("baseUrl") or raw.get("endpoint") or ""
        if api_key or base_url:
            sources.append({
                "name": str(raw.get("name") or f"relay-{index + 1}"),
                "base_url": str(base_url),
                "api_key": str(api_key),
                "model": str(raw.get("model") or existing.get("model") or DEFAULT_MODEL),
                "enabled": raw.get("enabled", True) is not False,
            })
    window = tk.Tk()
    window.title("Relay Imagegen 配置")
    window.resizable(False, False)
    frame = ttk.Frame(window, padding=16)
    frame.grid(sticky="nsew")
    status = tk.StringVar(value="按顺序尝试启用的中转站；失败时自动切换到下一个。")
    name_var = tk.StringVar()
    url_var = tk.StringVar()
    key_var = tk.StringVar()
    enabled_var = tk.BooleanVar(value=True)
    custom_label = "自定义模型（高级）"
    model_label = tk.StringVar()
    listbox = tk.Listbox(frame, height=6, width=32, exportselection=False)
    listbox.grid(row=0, column=0, rowspan=10, padx=(0, 16), sticky="ns")

    ttk.Label(frame, text="中转站名称").grid(row=0, column=1, sticky="w")
    ttk.Entry(frame, textvariable=name_var, width=45).grid(row=0, column=2, pady=(0, 6))
    ttk.Label(frame, text="中转站地址").grid(row=1, column=1, sticky="w")
    ttk.Entry(frame, textvariable=url_var, width=45).grid(row=1, column=2, pady=6)
    ttk.Label(frame, text="访问密钥").grid(row=2, column=1, sticky="w")
    ttk.Entry(frame, textvariable=key_var, show="*", width=45).grid(row=2, column=2, pady=6)
    ttk.Label(frame, text="生成模型").grid(row=3, column=1, sticky="w")
    model_combo = ttk.Combobox(frame, textvariable=model_label, values=list(MODEL_PRESETS) + [custom_label], state="readonly", width=42)
    model_combo.grid(row=3, column=2, pady=6)
    custom_model = tk.StringVar()
    custom_entry = ttk.Entry(frame, textvariable=custom_model, width=45)
    model_ids_by_label = dict(MODEL_PRESETS)
    discovered_models: list[str] = []
    show_all_models = tk.BooleanVar(value=False)
    model_status = tk.StringVar(value="填写地址和密钥后自动获取模型；也可手动刷新。")
    model_tools = ttk.Frame(frame)
    model_tools.grid(row=5, column=1, columnspan=2, sticky="w", pady=(8, 0))
    model_feedback = ttk.Label(frame, textvariable=model_status, wraplength=420)
    model_feedback.grid(row=6, column=1, columnspan=2, sticky="w", pady=(6, 8))
    results: queue.Queue = queue.Queue()
    model_cache: dict[tuple[str, str], list[str]] = {}
    attempted: set[tuple[str, str]] = set()
    busy = False
    pending_fetch: str | None = None

    def credentials_id() -> tuple[str, str]:
        return (url_var.get().strip(), hashlib.sha256(key_var.get().strip().encode()).hexdigest())

    def selected_model() -> str:
        return custom_model.get().strip() if model_label.get() == custom_label else model_ids_by_label.get(model_label.get(), "")

    def update_model_options() -> None:
        current = selected_model()
        candidates = discovered_models if show_all_models.get() else likely_image_models(discovered_models)
        model_ids_by_label.clear()
        model_ids_by_label.update(MODEL_PRESETS)
        model_ids_by_label.update({f"上游 · {model}": model for model in candidates})
        model_combo.configure(values=list(model_ids_by_label) + [custom_label])
        if current in candidates:
            model_label.set(f"上游 · {current}")
        elif current in MODEL_PRESETS.values():
            model_label.set(next(label for label, model in MODEL_PRESETS.items() if model == current))
        elif current:
            model_label.set(custom_label)
            custom_model.set(current)
        # Preserve the chosen ID even when filtering, changing credentials, or refreshing.
        select_preset(focus=False)

    def request_models(manual: bool = False) -> None:
        nonlocal busy
        identity = credentials_id()
        url, key = url_var.get().strip(), key_var.get().strip()
        if busy or not url or not key:
            if manual and (not url or not key):
                model_status.set("请先填写中转站地址和访问密钥。")
            return
        if not manual and identity in model_cache:
            discovered_models[:] = model_cache[identity]
            update_model_options()
            model_status.set(f"已加载 {len(discovered_models)} 个上游模型。名称筛选不代表已验证生图能力。")
            return
        if not manual and identity in attempted:
            return
        attempted.add(identity)
        busy = True
        fetch_button.configure(state="disabled")
        model_status.set("正在获取上游模型…窗口仍可操作。")

        def worker() -> None:
            try:
                results.put((identity, fetch_upstream_models(url, key), None))
            except Exception as exc:
                # Only our fixed ValueError messages may reach the UI.
                message = str(exc) if isinstance(exc, ModelDiscoveryError) else "无法读取模型列表，请检查地址或稍后刷新。"
                results.put((identity, None, message))
        threading.Thread(target=worker, daemon=True).start()

    def poll_models() -> None:
        nonlocal busy
        try:
            identity, models, error = results.get_nowait()
        except queue.Empty:
            pass
        else:
            busy = False
            fetch_button.configure(state="normal")
            if identity == credentials_id():
                if error:
                    model_status.set(error)
                else:
                    model_cache[identity] = models
                    discovered_models[:] = models
                    update_model_options()
                    model_status.set(f"已获取 {len(models)} 个模型；优先显示疑似生图模型，可勾选查看全部。列表不保证生图接口兼容。" if models else "上游返回空模型列表，可手动填写模型 ID。")
            else:
                request_models()
        window.after(100, poll_models)

    def schedule_models(*_args: object) -> None:
        nonlocal pending_fetch
        if pending_fetch is not None:
            window.after_cancel(pending_fetch)
        discovered_models.clear()
        update_model_options()
        model_status.set("地址和密钥填写完整后将自动获取模型。")
        pending_fetch = window.after(1000, run_scheduled_fetch)

    def run_scheduled_fetch() -> None:
        nonlocal pending_fetch
        pending_fetch = None
        request_models()

    fetch_button = ttk.Button(model_tools, text="获取 / 刷新上游模型", command=lambda: request_models(manual=True))
    fetch_button.grid(row=0, column=0, padx=(0, 12))
    ttk.Checkbutton(model_tools, text="显示全部模型", variable=show_all_models, command=update_model_options).grid(row=0, column=1)
    ttk.Label(frame, text="模型 ID").grid(row=4, column=1, sticky="w")
    ttk.Checkbutton(frame, text="启用此源", variable=enabled_var).grid(row=7, column=1, sticky="w", pady=4)

    def refresh() -> None:
        listbox.delete(0, tk.END)
        for source in sources:
            marker = "启用" if source.get("enabled", True) else "停用"
            listbox.insert(tk.END, f"[{marker}] {source['name']}")

    def load_selected(_event: object = None) -> None:
        selection = listbox.curselection()
        if not selection:
            return
        source = sources[selection[0]]
        name_var.set(source["name"])
        url_var.set(source["base_url"])
        key_var.set(source["api_key"])
        enabled_var.set(source.get("enabled", True) is not False)
        model = source.get("model") or DEFAULT_MODEL
        label = next((label for label, value in model_ids_by_label.items() if value == model), custom_label)
        model_label.set(label)
        custom_model.set(model if label == custom_label else "")
        if label == custom_label:
            custom_entry.grid(row=4, column=2, pady=6)
        else:
            custom_entry.grid_remove()

    def select_preset(_event: object = None, *, focus: bool = True) -> None:
        if model_label.get() == custom_label:
            custom_entry.grid(row=4, column=2, pady=6)
            if focus:
                custom_entry.focus_set()
        else:
            custom_entry.grid_remove()

    def form_source() -> dict[str, Any] | None:
        url = url_var.get().strip()
        key = key_var.get().strip()
        try:
            parsed_url = urlsplit(url)
            valid_url = parsed_url.scheme in {"http", "https"} and bool(parsed_url.hostname)
            if parsed_url.port is not None:
                valid_url = valid_url and 0 < parsed_url.port < 65536
        except ValueError:
            valid_url = False
        if not url or not key or not valid_url:
            messagebox.showerror("无法保存", "请填写有效的中转站地址和访问密钥。", parent=window)
            return None
        model = selected_model()
        if not model:
            messagebox.showerror("无法保存", "请输入模型 ID。", parent=window)
            return None
        return {"name": name_var.get().strip() or f"relay-{len(sources) + 1}", "base_url": normalize_openai_base_url(url), "api_key": key, "model": model, "enabled": enabled_var.get()}

    def add_or_update() -> None:
        source = form_source()
        if source is None:
            return
        # The explicit add action always appends; edits are committed by Save.
        sources.append(source)
        refresh()
        listbox.selection_clear(0, tk.END)
        listbox.selection_set(len(sources) - 1)
        load_selected()

    def delete_selected() -> None:
        selection = listbox.curselection()
        if selection and len(sources) > 1:
            sources.pop(selection[0])
            refresh()
            listbox.selection_set(min(selection[0], len(sources) - 1))
            load_selected()

    def move_selected(delta: int) -> None:
        selection = listbox.curselection()
        if not selection:
            return
        index = selection[0]
        target = index + delta
        if 0 <= target < len(sources):
            sources[index], sources[target] = sources[target], sources[index]
            refresh()
            listbox.selection_set(target)
            load_selected()

    def save() -> None:
        source = form_source()
        if source is None:
            return
        selection = listbox.curselection()
        if source is not None and selection:
            sources[selection[0]] = source
            saved_index = selection[0]
        elif source is not None:
            sources.append(source)
            saved_index = len(sources) - 1
        if not sources or not any(item.get("enabled", True) for item in sources) or not all(item.get("base_url") and item.get("api_key") for item in sources):
            messagebox.showerror("无法保存", "请补全每个中转站的地址和访问密钥。", parent=window)
            return
        try:
            ROOT_CONFIG.write_text(json.dumps({"sources": sources, "model": sources[0].get("model", DEFAULT_MODEL)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("保存失败", f"无法保存配置文件：{exc}", parent=window)
            return
        refresh()
        listbox.selection_set(saved_index)
        status.set("配置已保存。生成时会按列表顺序自动尝试。")
        messagebox.showinfo("已保存", "配置已保存，之后生成图片时会自动使用。", parent=window)

    ttk.Button(frame, text="添加新源", command=add_or_update).grid(row=8, column=1, pady=(12, 4), sticky="w")
    ttk.Button(frame, text="删除选中", command=delete_selected).grid(row=8, column=2, pady=(12, 4), sticky="w")
    ttk.Button(frame, text="上移", command=lambda: move_selected(-1)).grid(row=9, column=1, pady=4, sticky="w")
    ttk.Button(frame, text="下移", command=lambda: move_selected(1)).grid(row=9, column=2, pady=4, sticky="w")
    ttk.Label(frame, textvariable=status, foreground="#666", wraplength=420).grid(row=10, column=1, columnspan=2, sticky="w", pady=(8, 12))
    buttons = ttk.Frame(frame)
    buttons.grid(row=11, column=1, columnspan=2, sticky="e")
    ttk.Button(buttons, text="保存配置", command=save).grid(row=0, column=0, padx=(0, 8))
    ttk.Button(buttons, text="关闭", command=window.destroy).grid(row=0, column=1)
    listbox.bind("<<ListboxSelect>>", load_selected)
    model_combo.bind("<<ComboboxSelected>>", select_preset)
    url_var.trace_add("write", schedule_models)
    key_var.trace_add("write", schedule_models)
    window.after(100, poll_models)
    refresh()
    if sources:
        listbox.selection_set(0)
        load_selected()
    else:
        name_var.set("relay-1")
        model_label.set(MODEL_PRESETS.get(DEFAULT_MODEL, list(MODEL_PRESETS)[0]))
    window.mainloop()
    return 0


def open_gui() -> int:
    """Open the short first-run wizard; advanced multi-source editing is optional."""
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ImportError:
        print("Tkinter is not available in this Python installation.", file=sys.stderr)
        return 1

    loaded = load_json(ROOT_CONFIG, quiet=True)
    existing = loaded if isinstance(loaded, dict) else {}
    raw_sources = existing.get("sources") if isinstance(existing.get("sources"), list) else [existing]
    first = raw_sources[0] if raw_sources and isinstance(raw_sources[0], dict) else {}
    window = tk.Tk()
    window.title("Relay Imagegen 快速配置")
    window.resizable(False, False)
    frame = ttk.Frame(window, padding=20)
    frame.grid(sticky="nsew")
    ttk.Label(frame, text="配置一次，之后直接告诉 Codex 生成图片", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
    ttk.Label(frame, text="只需要填写中转站地址和密钥；模型会自动读取。", foreground="#666").grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 14))
    name_var = tk.StringVar(value=str(first.get("name") or "relay-1"))
    url_var = tk.StringVar(value=str(first.get("base_url") or first.get("baseUrl") or ""))
    key_var = tk.StringVar(value=str(first.get("api_key") or first.get("apiKey") or ""))
    model_var = tk.StringVar(value=str(first.get("model") or existing.get("model") or DEFAULT_MODEL))
    model_ids: dict[str, str] = dict(MODEL_PRESETS)
    discovered: list[str] = []
    status_var = tk.StringVar(value="填写地址和密钥后会自动获取模型。")
    results: queue.Queue = queue.Queue()
    busy = False
    pending: str | None = None

    def choose_model() -> str:
        return model_ids.get(model_var.get(), model_var.get().strip())

    def update_models() -> None:
        current = choose_model()
        model_ids.clear()
        model_ids.update(MODEL_PRESETS)
        candidates = likely_image_models(discovered) or discovered
        model_ids.update({f"上游 · {item}": item for item in candidates})
        combo.configure(values=list(model_ids))
        if current in candidates:
            model_var.set(f"上游 · {current}")
        elif current in MODEL_PRESETS.values():
            model_var.set(next(label for label, item in MODEL_PRESETS.items() if item == current))
        elif current:
            model_var.set(current)

    def request_models(manual: bool = False) -> None:
        nonlocal busy
        url, key = url_var.get().strip(), key_var.get().strip()
        if busy:
            return
        if not url or not key:
            if manual:
                status_var.set("请先填写中转站地址和访问密钥。")
            return
        busy = True
        refresh_button.configure(state="disabled")
        status_var.set("正在读取模型列表…")

        def worker() -> None:
            try:
                results.put((fetch_upstream_models(url, key), None))
            except Exception as exc:
                results.put((None, str(exc) if isinstance(exc, ModelDiscoveryError) else "读取失败，请检查地址或密钥。"))
        threading.Thread(target=worker, daemon=True).start()

    def poll() -> None:
        nonlocal busy
        try:
            models, error = results.get_nowait()
        except queue.Empty:
            pass
        else:
            busy = False
            refresh_button.configure(state="normal")
            if error:
                status_var.set(error + " 可直接选择预设或手动填写模型 ID。")
            else:
                discovered[:] = models
                update_models()
                status_var.set(f"已找到 {len(models)} 个模型；名称筛选仅供参考。" if models else "上游没有返回模型，可手动填写模型 ID。")
        window.after(100, poll)

    def schedule(*_args: object) -> None:
        nonlocal pending
        if pending is not None:
            window.after_cancel(pending)
        pending = window.after(700, request_models)

    def save() -> None:
        url, key = url_var.get().strip(), key_var.get().strip()
        try:
            parsed = urlsplit(url)
            valid = parsed.scheme in {"http", "https"} and bool(parsed.hostname)
        except ValueError:
            valid = False
        model = choose_model()
        if not valid or not key:
            messagebox.showerror("还差一步", "请填写有效的中转站地址和访问密钥。", parent=window)
            return
        if not model:
            messagebox.showerror("还差一步", "请选择或填写模型 ID。", parent=window)
            return
        source = {"name": name_var.get().strip() or "relay-1", "base_url": normalize_openai_base_url(url), "api_key": key, "model": model, "enabled": True}
        old_sources = [item for item in raw_sources[1:] if isinstance(item, dict)]
        try:
            ROOT_CONFIG.write_text(json.dumps({"sources": [source] + old_sources, "model": model}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("保存失败", f"无法保存配置：{exc}", parent=window)
            return
        messagebox.showinfo("配置完成", "已保存。现在可以直接让 Codex 生成图片了。", parent=window)
        window.destroy()

    def advanced() -> None:
        window.destroy()
        open_advanced_gui()

    ttk.Label(frame, text="中转站地址").grid(row=2, column=0, sticky="w", pady=5)
    ttk.Entry(frame, textvariable=url_var, width=46).grid(row=2, column=1, pady=5)
    ttk.Label(frame, text="访问密钥").grid(row=3, column=0, sticky="w", pady=5)
    ttk.Entry(frame, textvariable=key_var, show="*", width=46).grid(row=3, column=1, pady=5)
    ttk.Label(frame, text="生成模型").grid(row=4, column=0, sticky="w", pady=5)
    combo = ttk.Combobox(frame, textvariable=model_var, values=list(model_ids), state="normal", width=43)
    combo.grid(row=4, column=1, pady=5)
    ttk.Label(frame, textvariable=status_var, foreground="#666", wraplength=430).grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 8))
    actions = ttk.Frame(frame)
    actions.grid(row=6, column=0, columnspan=2, sticky="e", pady=(4, 0))
    refresh_button = ttk.Button(actions, text="刷新模型", command=lambda: request_models(manual=True))
    refresh_button.grid(row=0, column=0, padx=(0, 8))
    ttk.Button(actions, text="高级配置", command=advanced).grid(row=0, column=1, padx=(0, 8))
    ttk.Button(actions, text="保存并完成", command=save).grid(row=0, column=2)
    url_var.trace_add("write", schedule)
    key_var.trace_add("write", schedule)
    window.after(100, poll)
    if url_var.get() and key_var.get():
        window.after(200, request_models)
    window.mainloop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Set up relay-imagegen private config.")
    parser.add_argument("command", nargs="?", choices=["config", "gui"], help="Create config or open the local configuration window.")
    parser.add_argument("--advanced", action="store_true", help="Open the multi-source configuration window.")
    parser.add_argument("--check", action="store_true", help="Check the first usable config without printing secrets.")
    parser.add_argument("--check-codex", action="store_true", help="Check the current Codex config/auth provider.")
    parser.add_argument("--codex-config", help="Override the Codex config.toml path.")
    parser.add_argument("--codex-auth", help="Override the Codex auth.json path.")
    parser.add_argument("--check-ccswitch", action="store_true", help="Check the current ccswitch Codex provider.")
    parser.add_argument("--ccswitch-db", help="Override the ccswitch SQLite database path.")
    parser.add_argument(
        "--scope",
        choices=["root", "skill", "user"],
        default="root",
        help="Where to write config with the config command. Default: root.",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite an existing config.")
    args = parser.parse_args()

    if args.check_codex:
        return check_codex(
            Path(args.codex_config) if args.codex_config else CODEX_CONFIG,
            Path(args.codex_auth) if args.codex_auth else CODEX_AUTH,
        )
    if args.check_ccswitch:
        return check_ccswitch(Path(args.ccswitch_db) if args.ccswitch_db else CCSWITCH_DB)
    if args.check or not args.command:
        return check()
    if args.command == "gui":
        return open_advanced_gui() if args.advanced else open_gui()
    target = ROOT_CONFIG if args.scope == "root" else SKILL_CONFIG if args.scope == "skill" else user_config_path()
    return write_config(target, args.force)


if __name__ == "__main__":
    raise SystemExit(main())
