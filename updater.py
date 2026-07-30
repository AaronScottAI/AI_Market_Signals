"""
Simple GitHub-based auto-updater. No accounts/servers of my own involved --
this just checks a plain-text VERSION file in a GitHub repo you control, and
if it's newer than what's installed, offers to download and install it.

--------------------------------------------------------------------------
ONE-TIME SETUP (do this once, on your end):
--------------------------------------------------------------------------
1. Create a free GitHub account if you don't have one: https://github.com/join
2. Create a new PUBLIC repository (e.g. named "robinhood_ai_dashboard").
   Public keeps this simple -- no login/token needed for the app to check
   it. Nothing sensitive lives in this codebase (no API keys, no
   credentials), so a public repo is fine.
3. Upload this whole project folder to that repo. Easiest way with no
   command line: on the repo's GitHub page, click "Add file" ->
   "Upload files", then drag the whole project folder's contents in
   (including the VERSION file) and commit.
4. In config.py, set:
       UPDATE_REPO_OWNER = "your-github-username"
       UPDATE_REPO_NAME  = "robinhood_ai_dashboard"   # or whatever you named it
       UPDATE_BRANCH     = "main"
5. Re-run setup_and_run.bat once so this configured version is what's
   actually installed and checking against your repo.

--------------------------------------------------------------------------
PUBLISHING AN UPDATE (every time after that):
--------------------------------------------------------------------------
1. Bump the version number in TWO places so they match:
     - the VERSION file (plain text, just the number, e.g. "1.1.0")
     - APP_VERSION in config.py
2. Push/upload the changed files to the same GitHub repo.
3. Done. Every computer running the app will notice next time it's
   launched (or when someone clicks "Check for Updates"), and can pull
   the update down with one click -- no manual zip/unzip needed.
--------------------------------------------------------------------------
"""
from __future__ import annotations
import glob
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import textwrap
import zipfile
import urllib.request
import urllib.error

import config


def _raw_url(path: str) -> str:
    return (
        f"https://raw.githubusercontent.com/{config.UPDATE_REPO_OWNER}/"
        f"{config.UPDATE_REPO_NAME}/{config.UPDATE_BRANCH}/{path}"
    )


def _zip_url() -> str:
    return (
        f"https://github.com/{config.UPDATE_REPO_OWNER}/{config.UPDATE_REPO_NAME}"
        f"/archive/refs/heads/{config.UPDATE_BRANCH}.zip"
    )


def is_configured() -> bool:
    return bool(config.UPDATE_REPO_OWNER) and bool(config.UPDATE_REPO_NAME)


def _parse_version(v: str) -> tuple:
    """'1.10.2' -> (1, 10, 2). Tolerant of stray text/whitespace."""
    parts = []
    for p in v.strip().split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def check_for_update(timeout: float = 6.0):
    """Returns (update_available: bool, latest_version: str | None, error: str | None)."""
    if not is_configured():
        return False, None, "not_configured"
    try:
        with urllib.request.urlopen(_raw_url("VERSION"), timeout=timeout) as resp:
            latest = resp.read().decode("utf-8").strip()
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return False, None, f"Couldn't check for updates: {exc}"

    if not latest:
        return False, None, "Remote VERSION file was empty or missing."

    is_newer = _parse_version(latest) > _parse_version(config.APP_VERSION)
    return is_newer, latest, None


def cleanup_stray_update_folders(app_dir: str):
    """Defensive cleanup, meant to be called once at app startup: removes
    any leftover market_dashboard_update_* scratch folders sitting inside
    app_dir from a previous update that didn't clean up after itself (e.g.
    an older version of this file, or an update interrupted mid-way)."""
    for path in glob.glob(os.path.join(app_dir, "market_dashboard_update_*")):
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)


def _safe_temp_base(app_dir: str) -> str:
    """A directory to build the update in, guaranteed to be outside app_dir
    AND actually writable -- not just assumed to be. tempfile.gettempdir()
    can fall back to somewhere unusable in some Windows environments, so
    this tries several real candidate locations in order and verifies each
    one by actually writing a test file to it, rather than trusting that
    os.makedirs() not raising means it'll really work."""
    app_dir_abs = os.path.abspath(app_dir)

    candidates = []
    try:
        candidates.append(os.path.abspath(tempfile.gettempdir()))
    except Exception:
        pass
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(os.path.join(local_appdata, "MarketSignalDashboardTmp"))
    candidates.append(os.path.join(os.path.expanduser("~"), "AppData", "Local", "Temp"))
    candidates.append(os.path.join(os.path.expanduser("~"), ".market_dashboard_tmp"))

    last_error = None
    for candidate in candidates:
        if candidate == app_dir_abs or candidate.startswith(app_dir_abs + os.sep):
            continue  # never use a location inside the app's own folder
        try:
            os.makedirs(candidate, exist_ok=True)
            probe_path = os.path.join(candidate, ".write_test")
            with open(probe_path, "w") as f:
                f.write("test")
            os.remove(probe_path)
            return candidate
        except Exception as exc:
            last_error = exc
            continue

    raise RuntimeError(
        f"Couldn't find a writable temporary folder for the update "
        f"(tried {len(candidates)} locations). Last error: {last_error}"
    )


def apply_update_and_relaunch(app_dir: str, timeout: float = 60.0):
    """Downloads the latest version, writes a small helper script that
    waits for this process to exit then swaps the files in and relaunches
    the app. Caller is responsible for quitting the application right
    after calling this (so the helper can safely write over the running
    app's own files)."""
    tmp_dir = tempfile.mkdtemp(prefix="market_dashboard_update_", dir=_safe_temp_base(app_dir))
    zip_path = os.path.join(tmp_dir, "update.zip")
    urllib.request.urlretrieve(_zip_url(), zip_path)

    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(tmp_dir)

    extracted_folder = os.path.join(tmp_dir, f"{config.UPDATE_REPO_NAME}-{config.UPDATE_BRANCH}")
    if not os.path.isdir(extracted_folder):
        candidates = [
            d for d in os.listdir(tmp_dir)
            if os.path.isdir(os.path.join(tmp_dir, d))
        ]
        if len(candidates) == 1:
            extracted_folder = os.path.join(tmp_dir, candidates[0])
        else:
            raise RuntimeError("Couldn't locate the extracted update's files.")

    helper_path = os.path.join(tmp_dir, "apply_update_helper.py")
    helper_code = textwrap.dedent(f"""
        import os, shutil, subprocess, sys, time

        time.sleep(2)  # give the main app a moment to fully exit
        shutil.copytree(
            {extracted_folder!r}, {app_dir!r},
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(".venv", ".git", "__pycache__"),
        )

        if os.name == "nt":
            python_exe = os.path.join({app_dir!r}, ".venv", "Scripts", "python.exe")
        else:
            python_exe = os.path.join({app_dir!r}, ".venv", "bin", "python")
        if not os.path.exists(python_exe):
            python_exe = sys.executable

        subprocess.Popen([python_exe, os.path.join({app_dir!r}, "main.py")], cwd={app_dir!r})

        # clean up the scratch download/extraction directory now that the
        # update has been applied -- avoids leaking a folder every update
        shutil.rmtree({tmp_dir!r}, ignore_errors=True)
    """)
    with open(helper_path, "w") as f:
        f.write(helper_code)

    creationflags = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
    subprocess.Popen([sys.executable, helper_path], creationflags=creationflags)
