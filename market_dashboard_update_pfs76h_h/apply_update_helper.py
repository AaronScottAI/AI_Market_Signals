
import os, shutil, subprocess, sys, time

time.sleep(2)  # give the main app a moment to fully exit
shutil.copytree(
    'C:\\Users\\atsut\\Favorites\\robinhood_ai_dashboard\\market_dashboard_update_pfs76h_h\\AI_Market_Signals-main', 'C:\\Users\\atsut\\Favorites\\robinhood_ai_dashboard',
    dirs_exist_ok=True,
    ignore=shutil.ignore_patterns(".venv", ".git", "__pycache__"),
)

if os.name == "nt":
    python_exe = os.path.join('C:\\Users\\atsut\\Favorites\\robinhood_ai_dashboard', ".venv", "Scripts", "python.exe")
else:
    python_exe = os.path.join('C:\\Users\\atsut\\Favorites\\robinhood_ai_dashboard', ".venv", "bin", "python")
if not os.path.exists(python_exe):
    python_exe = sys.executable

subprocess.Popen([python_exe, os.path.join('C:\\Users\\atsut\\Favorites\\robinhood_ai_dashboard', "main.py")], cwd='C:\\Users\\atsut\\Favorites\\robinhood_ai_dashboard')
