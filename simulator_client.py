import argparse
import copy
import json
import math
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

DEFAULT_URL = "http://127.0.0.1:8765"


class ClientError(Exception):
    pass


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def _reject_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")


def _json_object(body: bytes) -> dict[str, object]:
    try:
        value = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_reject_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as error:
        raise ClientError("server returned invalid JSON") from error
    if not isinstance(value, dict):
        raise ClientError("server response must be a JSON object")
    _check_finite(value)
    return value


def _check_finite(value: object) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ClientError("server returned a non-finite number")
    if isinstance(value, dict):
        for child in value.values():
            _check_finite(child)
    elif isinstance(value, list):
        for child in value:
            _check_finite(child)


def _local_base_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise ClientError("URL must use local HTTP without credentials") from error
    if (
        parsed.scheme.lower() != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ClientError("URL must use http://127.0.0.1 or http://localhost without credentials")
    return value.rstrip("/")


def _request_json(
    base_url: str,
    path: str,
    method: str = "GET",
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        try:
            body = json.dumps(payload, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise ClientError("request cannot be represented as strict JSON") from error
        headers["Content-Type"] = "application/json"
    request = Request(f"{base_url}{path}", data=body, headers=headers, method=method)
    try:
        opener = build_opener(ProxyHandler({}), NoRedirectHandler())
        with opener.open(request, timeout=10) as response:
            if response.status >= 300:
                raise ClientError(f"HTTP {response.status}: redirects are not followed")
            return _json_object(response.read())
    except HTTPError as error:
        if 300 <= error.code < 400:
            raise ClientError(f"HTTP {error.code}: redirects are not followed") from error
        response = _json_object(error.read())
        message = response.get("error")
        raise ClientError(
            f"HTTP {error.code}: {message if isinstance(message, str) else 'request failed'}"
        ) from error
    except (URLError, TimeoutError, OSError) as error:
        raise ClientError(f"local request failed: {error}") from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local Wildfire Sweep Mission Lab client")
    parser.add_argument("--url", default=DEFAULT_URL)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("catalog", help="print model metadata and frozen study summary")

    mission = commands.add_parser("mission", help="evaluate one synthetic alert")
    mission.add_argument("--point-km", type=float, nargs=2, required=True, metavar=("EAST", "NORTH"))
    mission.add_argument("--bases", type=int, choices=(9, 25))
    mission.add_argument("--wind-mps", type=float, nargs=2, metavar=("EAST", "NORTH"))
    mission.add_argument("--offline-base", type=int)

    replay = commands.add_parser("replay", help="read one captured case-season")
    replay.add_argument("--case", required=True)
    replay.add_argument("--season", type=int, required=True)
    return parser


def _mission_payload(base_url: str, arguments: argparse.Namespace) -> dict[str, object]:
    catalog = _request_json(base_url, "/api/catalog")
    defaults = catalog.get("defaults")
    if not isinstance(defaults, dict):
        raise ClientError("catalog response is missing mission defaults")
    payload = copy.deepcopy(defaults)
    payload["point_km"] = list(arguments.point_km)
    if arguments.bases is not None:
        payload["n_bases"] = arguments.bases
        payload["offline_base"] = arguments.offline_base
    elif arguments.offline_base is not None:
        payload["offline_base"] = arguments.offline_base
    if arguments.wind_mps is not None:
        payload["wind_mps"] = list(arguments.wind_mps)
    return payload


def _print_json(value: dict[str, object]) -> None:
    try:
        serialized = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2)
    except (TypeError, ValueError) as error:
        raise ClientError("response cannot be represented as strict JSON") from error
    sys.stdout.write(serialized + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    try:
        base_url = _local_base_url(arguments.url)
        if arguments.command == "catalog":
            result = _request_json(base_url, "/api/catalog")
        elif arguments.command == "mission":
            payload = _mission_payload(base_url, arguments)
            result = _request_json(base_url, "/api/mission", "POST", payload)
        else:
            query = urlencode({"case": arguments.case, "season": arguments.season})
            result = _request_json(base_url, f"/api/replay?{query}")
        _print_json(result)
        return 0
    except (ClientError, OSError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
