#!/usr/bin/env python3
"""Preview and confirm removal of GPX points by UTC time and/or country."""

import argparse
from copy import deepcopy
from datetime import date, datetime, time, timezone
import os
from pathlib import Path
import sys
import tempfile
from xml.etree import ElementTree as ET

import gpx_countries


def time_bound(value, end=False):
    if value is None:
        return None
    try:
        if len(value) == 10:
            return datetime.combine(date.fromisoformat(value), time.max if end else time.min,
                                    tzinfo=timezone.utc)
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise ValueError("use YYYY-MM-DD or an ISO timestamp with a timezone") from None


def resolve_countries(tokens, data):
    if tokens is None:
        return None
    aliases = {}
    for feature in data["features"]:
        properties = feature["properties"]
        name = properties.get("NAME_EN") or properties.get("ADMIN") or properties.get("name")
        code = next((properties[key] for key in ("ISO_A2_EH", "ISO_A2", "ADM0_A3")
                     if properties.get(key) not in (None, "", "-99")), "—")
        country = name, code
        for key in ("ISO_A2_EH", "ISO_A2", "ISO_A3_EH", "ISO_A3", "ADM0_A3",
                    "NAME_EN", "ADMIN", "NAME", "NAME_LONG", "name"):
            value = properties.get(key)
            if value not in (None, "", "-99"):
                aliases.setdefault(str(value).casefold(), set()).add(country)
    selected = set()
    for token in tokens:
        values = [token] if token.strip().casefold() in aliases else token.split(",")
        for value in values:
            value = value.strip()
            if not value:
                continue
            matches = aliases.get(value.casefold(), set())
            if len(matches) != 1:
                raise ValueError(f"unknown or ambiguous country: {value}; use its ISO code")
            selected.update(matches)
    if not selected:
        raise ValueError("provide at least one country name or code")
    return selected


def matches(point, lookup, start=None, end=None, countries=None):
    latitude, longitude, timestamp = point
    if start is not None or end is not None:
        if timestamp is None:
            return False
        if (start is not None and timestamp < start) or (end is not None and timestamp > end):
            return False
    return countries is None or lookup(latitude, longitude) in countries


def tracking_nodes(root, prefix):
    for child in root:
        if child.tag == prefix + "wpt":
            yield child
        elif child.tag == prefix + "rte":
            yield from child.findall(prefix + "rtept")
        elif child.tag == prefix + "trk":
            for segment in child.findall(prefix + "trkseg"):
                yield from segment.findall(prefix + "trkpt")


def split_sequence(container, point_tag, removed):
    groups, current = [], []
    for child in container:
        if child.tag != point_tag:
            continue
        if child in removed:
            if current:
                groups.append(current)
                current = []
        else:
            current.append(child)
    if current:
        groups.append(current)
    parts = []
    for group in groups or [[]]:
        part = ET.Element(container.tag, container.attrib)
        part.text, part.tail = container.text, container.tail
        keep = set(group)
        for child in container:
            if child.tag != point_tag:
                part.append(deepcopy(child))
            elif child in keep:
                part.append(child)
        parts.append(part)
    return parts


def remove_points(root, prefix, removed):
    for child in list(root):
        if child.tag == prefix + "wpt" and child in removed:
            root.remove(child)
        elif child.tag == prefix + "rte":
            if any(point in removed for point in child.findall(prefix + "rtept")):
                index = list(root).index(child)
                root.remove(child)
                for offset, part in enumerate(split_sequence(child, prefix + "rtept", removed)):
                    root.insert(index + offset, part)
        elif child.tag == prefix + "trk":
            for segment in list(child):
                if segment.tag != prefix + "trkseg":
                    continue
                if any(point in removed for point in segment.findall(prefix + "trkpt")):
                    index = list(child).index(segment)
                    child.remove(segment)
                    for offset, part in enumerate(split_sequence(segment, prefix + "trkpt", removed)):
                        child.insert(index + offset, part)


def write_new(tree, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            tree.write(handle, encoding="utf-8", xml_declaration=True)
            handle.close()
            os.link(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gpx", type=Path, help="input GPX; never modified")
    parser.add_argument("--start", help="inclusive UTC start date or timestamp with timezone")
    parser.add_argument("--end", help="inclusive UTC end; a date includes that entire day")
    parser.add_argument("--countries", nargs="+", metavar="COUNTRY", help="ISO codes or quoted country names")
    parser.add_argument("--country-data", type=Path, help="existing Natural Earth country GeoJSON (offline)")
    parser.add_argument("-o", "--output", type=Path, help="new output file; default: INPUT_pruned.gpx")
    parser.add_argument("--dry-run", action="store_true", help="preview only; no confirmation or output file")
    args = parser.parse_args(argv)
    if args.start is None and args.end is None and args.countries is None:
        parser.error("provide at least one filter: --start, --end, or --countries")
    output = args.output or args.gpx.with_name(args.gpx.stem + "_pruned.gpx")
    try:
        start, end = time_bound(args.start), time_bound(args.end, end=True)
        if start is not None and end is not None and start > end:
            raise ValueError("--start must not be after --end")
        if output.resolve() == args.gpx.resolve() or (
            output.exists() and args.gpx.exists() and output.samefile(args.gpx)
        ):
            raise ValueError("output must be a new file, separate from the input")
        if not args.dry_run and (output.exists() or output.is_symlink()):
            raise ValueError("output already exists; choose a new filename with --output")
        tree = ET.parse(args.gpx, parser=ET.XMLParser(target=ET.TreeBuilder(
            insert_comments=True, insert_pis=True
        )))
        root = tree.getroot()
        prefix = gpx_countries.gpx_prefix(root)
        nodes = list(tracking_nodes(root, prefix))
        points = [gpx_countries.point_info(node, prefix) for node in nodes]
        if not points:
            raise ValueError("GPX contains no track points, route points, or waypoints")
        data = gpx_countries.load_countries(
            args.country_data or gpx_countries.DEFAULT_COUNTRIES,
            download=args.country_data is None,
        )
        lookup = gpx_countries.country_lookup(data)
        countries = resolve_countries(args.countries, data)
        selected = [(node, point) for node, point in zip(nodes, points)
                    if matches(point, lookup, start, end, countries)]
        filters = []
        if start is not None:
            filters.append("time >= " + start.isoformat().replace("+00:00", "Z"))
        if end is not None:
            filters.append("time <= " + end.isoformat().replace("+00:00", "Z"))
        if countries is not None:
            filters.append("country in " + ", ".join(f"{name} ({code})" for name, code in sorted(countries)))
        print("Removal filters (AND): " + "; ".join(filters))
        print(f"Matching points to remove: {len(selected):,} of {len(points):,}")
        print(f"Output (new file required): {output}\n")
        print(gpx_countries.format_table(*gpx_countries.summarize(
            (point for _, point in selected), lookup
        )))
        if start is not None or end is not None:
            print(f"Untimed points excluded from time filter: {sum(point[2] is None for point in points):,}")
        if not selected:
            print("Nothing matches; no file written.")
            return 0
        if len(selected) == len(points):
            print("All recorded points match; the new GPX will have no tracking points.")
        if args.dry_run:
            if output.exists() or output.is_symlink():
                print("Output already exists; actual pruning requires a new filename with --output.")
            print("Preview only; no file written.")
            return 0
        if not sys.stdin.isatty():
            parser.exit(2, "Confirmation requires an interactive terminal; use --dry-run for previews.\n")
        try:
            confirmed = input("Type 'yes' to remove these points and write the new file: ").strip().casefold()
        except (EOFError, KeyboardInterrupt):
            confirmed = ""
        if confirmed != "yes":
            print("Cancelled; no file written.")
            return 0
        remove_points(root, prefix, {node for node, _ in selected})
        if prefix:
            ET.register_namespace("", prefix[1:-1])
        write_new(tree, output)
        print(f"Wrote {output}; kept {len(points) - len(selected):,} of {len(points):,} points. Input unchanged.")
    except (OSError, ValueError, ET.ParseError) as error:
        parser.exit(2, f"error: {error}\n")
    except (KeyError, TypeError, IndexError, AttributeError):
        parser.exit(2, "error: malformed country GeoJSON\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
