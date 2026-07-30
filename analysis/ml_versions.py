"""
Versioned model registry: every time a model is trained, it's saved as a
new version (never overwriting a previous one) and recorded in a small
JSON manifest alongside its backtested metrics. One version is marked
"active" -- that's the one analysis/ml_model.py loads for live
predictions. This lets the Model History tab show every past version's
stats and roll back to one that performed better.
"""
from __future__ import annotations
import json
import os
from datetime import datetime

import config


def _manifest_path(name: str) -> str:
    return os.path.join(config.ML_MODEL_DIR, f"{name}_manifest.json")


def _load_manifest(name: str) -> dict:
    path = _manifest_path(name)
    if not os.path.exists(path):
        return {"active_version": None, "versions": []}
    try:
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict) or "versions" not in data:
            return {"active_version": None, "versions": []}
        return data
    except (json.JSONDecodeError, OSError, ValueError):
        return {"active_version": None, "versions": []}


def _save_manifest(name: str, manifest: dict):
    os.makedirs(config.ML_MODEL_DIR, exist_ok=True)
    with open(_manifest_path(name), "w") as f:
        json.dump(manifest, f, indent=2)


def _next_version_id(manifest: dict) -> str:
    existing = {v["version"] for v in manifest["versions"]}
    n = 1
    while f"v{n}" in existing:
        n += 1
    return f"v{n}"


def register_version(name: str, model, metrics: dict, activate: bool = False) -> str:
    """Saves `model` as a new version file, records it + its metrics in the
    manifest, optionally makes it the active version (always activates if
    it's the very first version, since there's nothing else to serve
    predictions), and returns the new version id."""
    import joblib

    manifest = _load_manifest(name)
    version_id = _next_version_id(manifest)
    filename = f"{name}_{version_id}.joblib"
    os.makedirs(config.ML_MODEL_DIR, exist_ok=True)
    joblib.dump(model, os.path.join(config.ML_MODEL_DIR, filename))

    entry = {
        "version": version_id,
        "filename": filename,
        "trained_at": datetime.now().isoformat(),
        "metrics": metrics,
        "promoted": bool(activate),
    }
    manifest["versions"].append(entry)
    if activate or manifest.get("active_version") is None:
        manifest["active_version"] = version_id
    _save_manifest(name, manifest)
    _prune_old_versions(name)
    return version_id


def activate_version(name: str, version_id: str) -> bool:
    """Manually switch the active version (rollback or forward). Returns
    False if that version id doesn't exist."""
    manifest = _load_manifest(name)
    ids = {v["version"] for v in manifest["versions"]}
    if version_id not in ids:
        return False
    manifest["active_version"] = version_id
    _save_manifest(name, manifest)
    from analysis import ml_model
    ml_model._model_cache.pop(name, None)  # force a reload from disk next time it's used
    return True


def get_active_version(name: str) -> dict | None:
    manifest = _load_manifest(name)
    active_id = manifest.get("active_version")
    if active_id is None:
        return None
    for v in manifest["versions"]:
        if v["version"] == active_id:
            return v
    return None


def get_active_model_path(name: str) -> str | None:
    active = get_active_version(name)
    if active is None:
        return None
    path = os.path.join(config.ML_MODEL_DIR, active["filename"])
    return path if os.path.exists(path) else None


def list_versions(name: str) -> list:
    """All recorded versions for this model, newest-trained first."""
    manifest = _load_manifest(name)
    versions = list(manifest["versions"])
    versions.sort(key=lambda v: v.get("trained_at", ""), reverse=True)
    return versions


def _prune_old_versions(name: str):
    manifest = _load_manifest(name)
    versions = manifest["versions"]
    if len(versions) <= config.ML_VERSION_RETENTION:
        return
    versions_by_age = sorted(versions, key=lambda v: v.get("trained_at", ""))
    active_id = manifest.get("active_version")
    recent_ids = {v["version"] for v in versions_by_age[-config.ML_VERSION_RETENTION:]}

    keep, remove = [], []
    for v in versions_by_age:
        if v["version"] in recent_ids or v["version"] == active_id:
            keep.append(v)
        else:
            remove.append(v)

    for v in remove:
        path = os.path.join(config.ML_MODEL_DIR, v["filename"])
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    manifest["versions"] = keep
    _save_manifest(name, manifest)
