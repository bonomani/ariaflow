from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .bonjour import advertise_http_service
from .contracts import preflight, run_ucc
from .core import add_queue_item, aria2_ensure_daemon, load_queue
from .webapp import serve as serve_api


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ariaflow",
        description="Sequential aria2 queue driver with adaptive bandwidth control.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="enqueue a URL")
    add.add_argument("url")
    add.add_argument("--output")
    add.add_argument("--post-action-rule", default="pending")
    add.add_argument("--priority", type=int, default=0, help="higher = processed first")
    add.add_argument(
        "--mirror",
        action="append",
        dest="mirrors",
        help="additional mirror URL (repeatable)",
    )
    add.add_argument("--torrent-data", help="base64-encoded .torrent file content")
    add.add_argument("--metalink-data", help="base64-encoded metalink XML content")

    run = sub.add_parser("run", help="process the queue sequentially")
    run.add_argument("--port", type=int, default=6800)

    status = sub.add_parser("status", help="show queue state")
    status.add_argument("--json", action="store_true")

    pre = sub.add_parser("preflight", help="run UIC pre-flight checks")
    pre.add_argument("--json", action="store_true")

    ucc = sub.add_parser("ucc", help="run a structured UCC execution cycle")
    ucc.add_argument("--port", type=int, default=6800)
    ucc.add_argument("--json", action="store_true")

    api = sub.add_parser("serve", help="start the local API server")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8000)

    install = sub.add_parser("install", help="install ariaflow on macOS")
    install.add_argument("--dry-run", action="store_true")
    install.add_argument(
        "--with-aria2",
        action="store_true",
        help="also install the optional advanced aria2 launchd service",
    )

    uninstall = sub.add_parser(
        "uninstall", help="remove installed ariaflow components on macOS"
    )
    uninstall.add_argument("--dry-run", action="store_true")
    uninstall.add_argument(
        "--with-aria2",
        action="store_true",
        help="also remove the optional advanced aria2 launchd service",
    )

    sub.add_parser("lifecycle", help="show install and service status")

    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "add":
        item = add_queue_item(
            args.url,
            output=args.output,
            post_action_rule=args.post_action_rule,
            priority=args.priority,
            mirrors=args.mirrors,
            torrent_data=args.torrent_data,
            metalink_data=args.metalink_data,
        )
        print(f"Queued: {item.url} (mode={item.mode}, priority={item.priority})")
        return 0

    if args.command == "run":
        result = run_ucc(port=args.port)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["result"].get("failure_class") is None else 1

    if args.command == "status":
        items = load_queue()
        if args.json:
            print(json.dumps({"items": items}, indent=2, sort_keys=True))
        else:
            for item in items:
                print(f"{item.get('status', 'unknown'):>10}  {item.get('url')}")
        return 0

    if args.command == "preflight":
        result = preflight()
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            for gate in result["gates"]:
                state = "satisfied" if gate["satisfied"] else "not_satisfied"
                print(f"[GATE] {gate['name']} : {state} [{gate['blocking']}]")
            for pref in result["preferences"]:
                options = " | ".join(str(o) for o in pref.get("options", []))
                print(
                    f"[PREFERENCE] {pref['name']} : {pref.get('value', 'undeclared')} — options: {options}"
                )
        return result["exit_code"]

    if args.command == "ucc":
        result = run_ucc(port=args.port)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(json.dumps(result["result"], indent=2, sort_keys=True))
        return 0 if result["result"].get("failure_class") is None else 1

    if args.command == "serve":
        try:
            aria2_ensure_daemon()
        except Exception as exc:
            print(f"Unable to start aria2 runtime: {exc}", file=sys.stderr)
            return 1
        server = serve_api(host=args.host, port=args.port)
        print(f"Serving API on http://{args.host}:{args.port}")
        try:
            with advertise_http_service(
                role="api",
                port=args.port,
                path="/api/status",
                product="ariaflow",
                version=__version__,
            ):
                server.serve_forever()
        except KeyboardInterrupt:
            server.server_close()
        return 0

    if args.command == "install":
        from .install import install_all

        result = install_all(dry_run=args.dry_run, include_aria2=args.with_aria2)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.command == "uninstall":
        from .install import uninstall_all

        result = uninstall_all(dry_run=args.dry_run, include_aria2=args.with_aria2)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.command == "lifecycle":
        from .install import status_all

        print(json.dumps(status_all(), indent=2, sort_keys=True))
        return 0

    return 1
