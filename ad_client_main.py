from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(prog="ad-client")
    sub = parser.add_subparsers(dest="entry", required=True)

    sub.add_parser("cli", help="Run advertiser CLI")
    webui = sub.add_parser("webui", help="Run advertiser WebUI server")
    webui.add_argument("--host", default="127.0.0.1")
    webui.add_argument("--port", type=int, default=8081)

    if len(sys.argv) > 1 and sys.argv[1] == "cli":
        from ad_client.interfaces.cli.main import main as cli_main

        original_argv = sys.argv
        try:
            sys.argv = ["ad-client-cli", *sys.argv[2:]]
            return cli_main()
        finally:
            sys.argv = original_argv

    args = parser.parse_args()

    if args.entry == "webui":
        try:
            import uvicorn
        except ImportError:
            print("Please install dependencies first: pip install -r requirements.txt", file=sys.stderr)
            return 1
        uvicorn.run("ad_client.interfaces.webui.main:app", host=args.host, port=args.port, reload=False)
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
