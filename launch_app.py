import os
import subprocess
import sys
import time
import webbrowser

APP_URL = "http://127.0.0.1:5000"
ROOT = os.path.dirname(os.path.abspath(__file__))


def main():
    os.chdir(ROOT)
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT)
    time.sleep(2)
    try:
        webbrowser.open(APP_URL)
    except Exception:
        pass
    print(f"ShiftFlow app started. Open: {APP_URL}")
    print("Press Ctrl+C in this terminal to stop it.")
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        print("ShiftFlow app stopped.")


if __name__ == "__main__":
    main()
