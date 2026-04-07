from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(prog="seccomp-privacy-platform")
    sub = parser.add_subparsers(dest="entry", required=True)

    sub.add_parser("cli", help="Run client CLI")

    webui = sub.add_parser("webui", help="Run client WebUI server")
    webui.add_argument("--host", default="127.0.0.1")
    webui.add_argument("--port", type=int, default=8080)

    args, extra = parser.parse_known_args()

    if args.entry == "cli":
        from client.interfaces.cli.main import main as cli_main

        original_argv = sys.argv
        try:
            sys.argv = ["client-cli", *extra]
            return cli_main()
        finally:
            sys.argv = original_argv

    if args.entry == "webui":
        try:
            import uvicorn
        except ImportError as exc:
            print("Please install dependencies first: pip install -r client/requirements.txt", file=sys.stderr)
            return 1

        uvicorn.run("client.interfaces.webui.main:app", host=args.host, port=args.port, reload=False)
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
