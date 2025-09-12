from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
import os

import yaml


_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_CONFIG_PATH = _ROOT / "config.yml"
_MODULE_CONFIG_DIR = _ROOT / "config"


def _deep_merge_dicts(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge dict b into dict a and return a new dict.

    - If both values are dicts, merge them recursively.
    - Otherwise, value from b overrides a.
    """
    result: Dict[str, Any] = dict(a) if isinstance(a, dict) else {}
    for k, v in (b or {}).items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge_dicts(result[k], v)
        else:
            result[k] = v
    return result


class Config(dict):
    """Simple dict-like config accessor with defaults."""

    @property
    def command_prefix(self) -> str:
        return self.get("command_prefix", "!")

    @property
    def log_level(self) -> str:
        return self.get("log_level", "INFO")

    @property
    def guild_ids(self) -> list[int]:
        return [int(guild_id) for guild_id in self.get("guild_ids", []) or []]

    # --- Modular helpers ---
    def module(self, name: str) -> Dict[str, Any]:
        """Return a module namespace dict (e.g., config for 'verification').

        Example structure in YAML file config/verification.yml:
        verification:
          api:
            base_url: "https://api.example.com"
        """
        return self.get(name, {}) or {}


    # --- Feature toggles ---
    def _features_map(self) -> Dict[str, Any]:
        value = self.get("features", {}) or {}
        return value if isinstance(value, dict) else {}

    def is_feature_enabled(self, name: str) -> bool:
        """Whether a feature package under features/<name>/ is enabled.

        Defaults to True if not specified.
        """
        fmap = self._features_map()
        val = fmap.get(name)
        if isinstance(val, bool):
            return val
        return True


_CONFIG_SINGLETON: Config | None = None


def _load_config_from_disk(path: os.PathLike[str] | str | None = None) -> Config:
    """Read configuration files from disk and compose a Config instance."""
    cfg_path = Path(path) if path else _DEFAULT_CONFIG_PATH
    data: Dict[str, Any] = {}

    # Load global config first
    if cfg_path.exists():
        with cfg_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    # Load each module config (top-level files) and merge under its namespace
    if _MODULE_CONFIG_DIR.exists():
        # 1) Top-level module files: config/<module>.yml
        for yml in sorted(_MODULE_CONFIG_DIR.glob("*.yml")):
            try:
                with yml.open("r", encoding="utf-8") as f:
                    mod_data = yaml.safe_load(f) or {}
                # Expect a single top-level key equal to the module name
                for top_key, top_val in mod_data.items():
                    if not isinstance(top_val, dict):
                        continue
                    # Deep merge into namespace
                    current = data.get(top_key, {}) or {}
                    merged = _deep_merge_dicts(current, top_val)
                    data[top_key] = merged
            except Exception:
                # Ignore malformed module configs to avoid crashing startup
                continue

        # 2) Module subdirectories: config/<module>/**/*.yml
        for module_dir in sorted(p for p in _MODULE_CONFIG_DIR.iterdir() if p.is_dir()):
            module_name = module_dir.name
            # Collect and merge all YAML files recursively for this module
            for yml in sorted(module_dir.rglob("*.yml")):
                try:
                    with yml.open("r", encoding="utf-8") as f:
                        raw = yaml.safe_load(f) or {}
                    if not isinstance(raw, dict):
                        continue
                    # If file already names the module as top-level, use that; else, treat as fragment
                    if module_name in raw and isinstance(raw[module_name], dict):
                        fragment = raw[module_name]
                    else:
                        fragment = raw
                    current = data.get(module_name, {}) or {}
                    merged = _deep_merge_dicts(current, fragment)
                    data[module_name] = merged
                except Exception:
                    continue

    return Config(data)


def load_config(path: os.PathLike[str] | str | None = None, *, force_reload: bool = False) -> Config:
    """Return a cached Config instance.

    - On first call (or if force_reload=True), read from disk and cache.
    - Subsequent calls return the same in-memory Config to avoid repeated disk I/O.
    - If a custom path is provided, it will reload from that path and update the cache.
    """
    global _CONFIG_SINGLETON
    if not force_reload and path is None and _CONFIG_SINGLETON is not None:
        return _CONFIG_SINGLETON
    cfg = _load_config_from_disk(path)
    _CONFIG_SINGLETON = cfg
    return cfg


def reload_config(path: os.PathLike[str] | str | None = None) -> Config:
    """Force a re-read of configuration files and refresh the cached instance."""
    return load_config(path, force_reload=True)
