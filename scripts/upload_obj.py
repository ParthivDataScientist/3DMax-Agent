"""Upload a local OBJ file to the running 3DMax Agent server."""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


VALID_UNITS = ("mm", "cm", "m", "in")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload a local .obj file to 3DMax Agent and save the generated ZIP package."
    )
    parser.add_argument("obj_path", help="Path to the local .obj file.")
    parser.add_argument(
        "--unit",
        default="mm",
        choices=VALID_UNITS,
        help="Source unit used by the OBJ geometry. Defaults to mm.",
    )
    parser.add_argument(
        "--server",
        default="http://localhost:3000",
        help="Base URL of the running app. Defaults to http://localhost:3000.",
    )
    parser.add_argument(
        "--output-dir",
        default="downloads",
        help="Directory where the ZIP should be saved. Defaults to downloads/.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional exact ZIP output path. Overrides --output-dir.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=1200,
        help="Request timeout in seconds. Defaults to 1200.",
    )
    return parser.parse_args()


def read_obj_text(obj_path: Path) -> str:
    if not obj_path.exists():
        raise SystemExit(f"File not found: {obj_path}")
    if obj_path.suffix.lower() != ".obj":
        raise SystemExit("Only .obj files are supported.")
    return obj_path.read_text(encoding="utf-8", errors="replace")


def api_url(server: str) -> str:
    return server.rstrip("/") + "/api/process"


def parse_error_response(error: HTTPError) -> str:
    try:
        raw = error.read().decode("utf-8", errors="replace")
        payload = json.loads(raw)
        return payload.get("detail") or payload.get("error") or raw
    except Exception:
        return str(error)


def upload_obj(args: argparse.Namespace) -> dict:
    obj_path = Path(args.obj_path).expanduser()
    content = read_obj_text(obj_path)
    body = json.dumps(
        {
            "filename": obj_path.name,
            "content": content,
            "sourceUnit": args.unit,
        }
    ).encode("utf-8")
    request = Request(
        api_url(args.server),
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=args.timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise SystemExit(f"Upload failed ({error.code}): {parse_error_response(error)}") from error
    except URLError as error:
        raise SystemExit(f"Could not reach server at {args.server}: {error.reason}") from error


def output_path(args: argparse.Namespace, zip_filename: str) -> Path:
    if args.output:
        return Path(args.output).expanduser()
    return Path(args.output_dir).expanduser() / zip_filename


def save_zip(args: argparse.Namespace, response_payload: dict) -> Path:
    zip_b64 = response_payload.get("zipBase64")
    zip_filename = response_payload.get("filename") or "fabrication_package.zip"
    if not zip_b64:
        raise SystemExit("Server response did not include a ZIP payload.")

    destination = output_path(args, zip_filename)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(base64.b64decode(zip_b64))
    return destination


def main() -> int:
    args = parse_args()
    response_payload = upload_obj(args)
    destination = save_zip(args, response_payload)

    print(f"Saved ZIP: {destination}")
    print(f"Components: {response_payload.get('componentCount', '-')}")
    print(f"Part groups: {response_payload.get('partGroupCount', '-')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
