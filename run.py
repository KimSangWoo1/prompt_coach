#!/usr/bin/env python3
"""Run with Python 3.11+; no pip install is required."""
import argparse
import threading
import webbrowser
from pathlib import Path
from promptcoach.server import create_server

def main():
    p = argparse.ArgumentParser(description="Prompt Coach — local prompt practice")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parent / "data")
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args()
    try:
        server = create_server(args.data_dir, args.port)
    except (OSError, ValueError) as e:
        p.exit(1, f"시작 실패: {e}\n다른 포트로 실행하거나 data 폴더를 확인해 주세요.\n")
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Prompt Coach: {url}\n데이터: {args.data_dir.resolve()}\n종료: Ctrl+C")
    if not args.no_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__ == "__main__": main()
