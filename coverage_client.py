import argparse
import sys
from urllib.parse import urlencode

from simulator_client import (
    ClientError,
    DEFAULT_URL,
    _local_base_url,
    _print_json,
    _request_json,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local Wildfire Coverage Atlas client")
    parser.add_argument("--base-url", default=DEFAULT_URL)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("catalog", help="print the captured coverage catalog")

    case = commands.add_parser("case", help="read one captured coverage case")
    case.add_argument("--case", required=True, metavar="ID", help="case identifier from the catalog")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    try:
        base_url = _local_base_url(arguments.base_url)
        if arguments.command == "catalog":
            result = _request_json(base_url, "/api/coverage/catalog")
        else:
            query = urlencode({"case": arguments.case})
            result = _request_json(base_url, f"/api/coverage?{query}")
        _print_json(result)
        return 0
    except (ClientError, OSError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
