"""Command-line adapter for Timeline conversion and atomic GPX file output."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from boboji import __version__
from boboji.gpx import to_gpx
from boboji.timeline import ConversionError, combine, convert_history


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="timeline_to_fog.py",
        description="Convert Google Maps Timeline JSON to Fog of World GPX, entirely offline.",
    )
    parser.add_argument("inputs", type=Path, nargs="+", help="one or more exported JSON files (extract Takeout ZIPs first)")
    parser.add_argument("-o", "--output", type=Path, required=True, help="destination .gpx file")
    parser.add_argument("--max-gap-minutes", type=float, default=30, help="start a new track after this time gap (default: 30)")
    parser.add_argument("--max-distance-km", type=float, default=10, help="start a new track after this distance, at most 10 km (default: 10)")
    parser.add_argument("--force", action="store_true", help="replace an existing output file")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _reject_constant(_: str) -> None:
    raise ConversionError("JSON contains a non-finite number")


def _write_output(output: Path, content: bytes, *, force: bool) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=f".{output.name}.", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if force:
            os.replace(temporary, output)
        else:
            # An atomic create prevents a racing process from being overwritten.
            os.link(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argument_parser()
    args = parser.parse_args(argv)
    try:
        if args.output.suffix.lower() != ".gpx":
            raise ConversionError("output filename must end in .gpx")
        for path in args.inputs:
            if path.resolve() == args.output.resolve() or (
                args.output.exists() and path.exists() and path.samefile(args.output)
            ):
                raise ConversionError("output must not replace an input file")
        if args.output.exists() and not args.force:
            raise ConversionError("output already exists; choose another filename or use --force")
        conversions = []
        for path in args.inputs:
            try:
                with path.open(encoding="utf-8-sig") as handle:
                    document = json.load(handle, parse_constant=_reject_constant)
                conversions.append(convert_history(
                    document,
                    max_gap_minutes=args.max_gap_minutes,
                    max_distance_km=args.max_distance_km,
                ))
            except json.JSONDecodeError as error:
                raise ConversionError(f"{path}: invalid JSON at line {error.lineno}, column {error.colno}") from None
            except UnicodeError:
                raise ConversionError(f"{path}: expected a UTF-8 JSON export") from None
            except ConversionError as error:
                raise ConversionError(f"{path}: {error}") from None
        conversion = combine(conversions)
        _write_output(args.output, to_gpx(conversion), force=args.force)
    except (ConversionError, OSError) as error:
        parser.exit(2, f"{parser.prog}: error: {error}\n")
    print(f"Converted {conversion.point_count} recorded points into {len(conversion.tracks)} track segments: {args.output}")
    return 0
