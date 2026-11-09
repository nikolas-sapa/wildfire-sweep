import argparse
import json
import os
import sys
from pathlib import Path

import capture_integrity


def validate_output_path(output_path: Path) -> None:
    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError(f"output already exists: {output_path}")
    if not output_path.parent.is_dir():
        raise FileNotFoundError(
            f"output parent directory does not exist: {output_path.parent}"
        )


def write_new_json(output_path: Path, text: str) -> None:
    descriptor = os.open(
        output_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o644,
    )
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(text.encode("utf-8"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args(argv)
    try:
        if arguments.output is not None:
            validate_output_path(arguments.output)
        receipt = capture_integrity.verify_capture(str(arguments.directory))
        text = json.dumps(receipt, indent=2, allow_nan=False) + "\n"
        if arguments.output is None:
            sys.stdout.write(text)
        else:
            write_new_json(arguments.output, text)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
