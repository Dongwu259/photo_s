"""
PhotoS - `plugin` subcommand logic.

Installs / uninstalls / inspects official optional plugins. Official plugins
are separate PyPI distributions (``photo-s-plugin-<name>``); large model
weights are downloaded on first use via :mod:`photo_s.modelstore`.

Conventions (match the rest of the CLI):
  * ``--json`` mode: stdout carries ONLY the JSON contract; all human /
    diagnostic text goes to stderr.
  * human mode: plain text on stdout.
Pip is invoked as a subprocess so the ``--json`` contract works even when pip
is missing (machine-readable error, never a crash).
"""

import json
import subprocess
import sys
from typing import List, Optional

from .plugin import discover_plugins
from .registry import OFFICIAL_PLUGINS, get_official, to_dict


def _pip_run(argv: List[str]) -> subprocess.CompletedProcess:
    """Run pip in the current interpreter. May raise FileNotFoundError."""
    return subprocess.run(
        [sys.executable, "-m", "pip", "--disable-pip-version-check", *argv],
        capture_output=True, text=True)


def _installed_version(dist: str) -> Optional[str]:
    """Best-effort installed version of a distribution. None if absent."""
    try:
        from importlib.metadata import version
        return version(dist)
    except Exception:
        return None


def _installed_plugins():
    """Map entry-point name → plugin object for currently loaded plugins."""
    out = {}
    for p in discover_plugins():
        out[p.name] = p
    return out


def _json(obj, use_json: bool) -> None:
    if use_json:
        print(json.dumps(obj, indent=2, ensure_ascii=False))


# ── subcommand implementations ─────────────────────────────────────────────


def _cmd_list(parsed) -> int:
    use_json = getattr(parsed, "json", False)
    installed_objs = _installed_plugins()
    installed = []
    for name, plugin in installed_objs.items():
        ver = _installed_version("photo-s-plugin-" + name)
        installed.append({
            "name": name,
            "provides": list(getattr(plugin, "provides", ())),
            "version": ver,
        })

    available = []
    for name, official in OFFICIAL_PLUGINS.items():
        entry = to_dict(official)
        entry["installed"] = name in installed_objs
        available.append(entry)

    if use_json:
        _json({"installed": installed, "available": available}, True)
        return 0

    if installed:
        print("📦 已安装插件 Installed plugins:")
        for i in installed:
            provides = ", ".join(i["provides"]) or "-"
            ver = " (v{})".format(i["version"]) if i.get("version") else ""
            print("   {}  [{}]{}{}".format(i["name"], provides, ver,
                                           "  🔌" if i["provides"] else ""))
    else:
        print("📦 已安装插件 Installed plugins: （无 none）")
    print()
    print("📦 官方插件 Official plugins (photo-s plugin install <name>):")
    for a in available:
        mark = "✅ 已装 installed" if a["installed"] else "·"
        print("   {:>12}  {}  {}".format(a["name"], mark, a["description"]))
    if use_json is False:
        print()
        print("安装 Install:  photo-s plugin install <name>  或  pip install <pypi_distribution>")
    return 0


def _cmd_install(parsed) -> int:
    name = parsed.name
    use_json = getattr(parsed, "json", False)
    dry_run = getattr(parsed, "dry_run", False)

    official = get_official(name)
    if official is None:
        if use_json:
            print(json.dumps({"ok": False, "name": name,
                              "error": "not in official registry"}, indent=2))
        else:
            print("❌ 未知官方插件 Unknown official plugin: {}".format(name))
            print("   可用列表 Available: photo-s plugin list")
        return 1

    dist = official.pypi_distribution
    if name in _installed_plugins():
        if use_json:
            print(json.dumps({"ok": True, "name": name,
                              "already_installed": True}, indent=2))
        else:
            print("✅ 已安装 Already installed: {}".format(dist))
        return 0

    argv = ["install", "--quiet", dist]
    if dry_run:
        if use_json:
            print(json.dumps({"ok": True, "name": name, "dry_run": True,
                              "pip_argv": [sys.executable, "-m", "pip", *argv]},
                             indent=2))
        else:
            print("(dry-run) 将执行 will run: pip install {}".format(dist))
        return 0

    try:
        proc = _pip_run(argv)
    except FileNotFoundError:
        if use_json:
            print(json.dumps({"ok": False, "name": name,
                              "error": "pip not available",
                              "detail": "no pip in {}".format(sys.executable)},
                             indent=2))
        else:
            print("❌ pip 不可用 pip not available: 请用 pip install {} 手动安装"
                  .format(dist))
        return 1

    if proc.returncode != 0:
        detail = (proc.stderr or "").strip()[-400:]
        if use_json:
            print(json.dumps({"ok": False, "name": name,
                              "error": "pip install failed",
                              "detail": detail}, indent=2))
        else:
            print("❌ 安装失败 Install failed: {}".format(dist))
            if detail:
                print("   " + detail.splitlines()[-1])
        return 1

    ver = _installed_version(dist)
    if use_json:
        payload = {"ok": True, "name": name, "distribution": dist}
        if ver:
            payload["version"] = ver
        print(json.dumps(payload, indent=2))
    else:
        print("✅ 已安装 Installed: {} (v{})".format(dist, ver or "?"))
    return 0


def _cmd_uninstall(parsed) -> int:
    name = parsed.name
    use_json = getattr(parsed, "json", False)
    dry_run = getattr(parsed, "dry_run", False)

    official = get_official(name)
    dist = official.pypi_distribution if official else "photo-s-plugin-" + name

    argv = ["uninstall", "-y", dist]
    if dry_run:
        if use_json:
            print(json.dumps({"ok": True, "name": name, "dry_run": True,
                              "pip_argv": [sys.executable, "-m", "pip", *argv]},
                             indent=2))
        else:
            print("(dry-run) 将执行 will run: pip uninstall -y {}".format(dist))
        return 0

    try:
        proc = _pip_run(argv)
    except FileNotFoundError:
        if use_json:
            print(json.dumps({"ok": False, "name": name,
                              "error": "pip not available"}, indent=2))
        else:
            print("❌ pip 不可用 pip not available")
        return 1

    if proc.returncode != 0:
        detail = (proc.stderr or "").strip()[-400:]
        if use_json:
            print(json.dumps({"ok": False, "name": name,
                              "error": "pip uninstall failed",
                              "detail": detail}, indent=2))
        else:
            print("❌ 卸载失败 Uninstall failed: {}".format(dist))
        return 1

    if use_json:
        print(json.dumps({"ok": True, "name": name, "distribution": dist},
                         indent=2))
    else:
        print("✅ 已卸载 Uninstalled: {}".format(dist))
    return 0


def _cmd_info(parsed) -> int:
    name = parsed.name
    use_json = getattr(parsed, "json", False)

    installed_objs = _installed_plugins()
    official = get_official(name)
    if official is None and name not in installed_objs:
        if use_json:
            print(json.dumps({"ok": False, "name": name,
                              "error": "unknown plugin"}, indent=2))
        else:
            print("❌ 未知插件 Unknown plugin: {}".format(name))
        return 1

    payload = {"name": name}
    if official is not None:
        payload.update(to_dict(official))
    payload["installed"] = name in installed_objs
    payload["version"] = _installed_version(
        official.pypi_distribution if official else "photo-s-plugin-" + name)
    if name in installed_objs:
        plugin = installed_objs[name]
        payload["provides"] = list(getattr(plugin, "provides", ()))
        specs = plugin.weight_specs()
        if specs:
            from .modelstore import status
            payload["weights"] = [status(s) for s in specs]

    if use_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("📦 插件 Plugin: {}".format(name))
        print("   已安装 installed:", "✅" if payload["installed"] else "❌")
        if payload.get("version"):
            print("   版本 version:", payload["version"])
        if payload.get("provides"):
            print("   提供 provides:", ", ".join(payload["provides"]))
        if payload.get("description"):
            print("   描述 desc:", payload["description"])
        if payload.get("pypi_distribution"):
            print("   PyPI 包:", payload["pypi_distribution"])
        if "weights" in payload:
            print("   模型权重 weights:")
            for w in payload["weights"]:
                mark = "✅ 已缓存 cached" if w["cached"] else "· 未下载"
                print("      {}  {}".format(w["name"], mark))
    return 0


def _cmd_fetch(parsed) -> int:
    name = parsed.name
    use_json = getattr(parsed, "json", False)

    installed_objs = _installed_plugins()
    plugin = installed_objs.get(name)
    if plugin is None:
        if use_json:
            print(json.dumps({"ok": False, "name": name,
                              "error": "plugin not installed",
                              "detail": "run 'photo-s plugin install {}' first"
                              .format(name)}, indent=2))
        else:
            print("❌ 插件未安装 Not installed: {}".format(name))
            print("   先安装 First install: photo-s plugin install {}"
                  .format(name))
        return 1

    from .modelstore import ensure
    specs = plugin.weight_specs()
    if not specs:
        if use_json:
            print(json.dumps({"ok": True, "name": name, "weights": []},
                             indent=2))
        else:
            print("✅ 该插件无模型权重 No weights for this plugin")
        return 0

    results = []
    for spec in specs:
        if not use_json:
            print("⏬ 下载权重 Fetching {} …".format(spec.name), file=sys.stderr)
        try:
            path = ensure(spec)
            results.append({"name": spec.name, "path": path, "cached": True})
        except RuntimeError as e:
            if use_json:
                print(json.dumps({"ok": False, "name": name,
                                  "error": "weight download failed",
                                  "detail": str(e)}, indent=2))
            else:
                print("❌ 权重下载失败 Weight download failed: {}".format(e))
            return 1

    if use_json:
        print(json.dumps({"ok": True, "name": name, "weights": results},
                         indent=2))
    else:
        for w in results:
            print("✅ 已就绪 Ready: {} → {}".format(w["name"], w["path"]))
    return 0


# ── entry point ────────────────────────────────────────────────────────────


def run(parsed) -> int:
    """Dispatch a parsed `plugin` subcommand to its handler. Returns exit code."""
    action = getattr(parsed, "plugin_action", None)
    handler = {
        "list": _cmd_list,
        "install": _cmd_install,
        "uninstall": _cmd_uninstall,
        "info": _cmd_info,
        "fetch": _cmd_fetch,
    }.get(action)
    if handler is None:
        print("plugin: 未知子命令 unknown action: {}".format(action),
              file=sys.stderr)
        return 2
    return handler(parsed)
