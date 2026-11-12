"""Serialize recorded tracks as GPX 1.1 for Fog of World."""

from __future__ import annotations

from decimal import Decimal
from xml.etree import ElementTree as ET

from boboji.timeline import Conversion

NAMESPACE = "http://www.topografix.com/GPX/1/1"


def to_gpx(conversion: Conversion) -> bytes:
    ET.register_namespace("", NAMESPACE)

    def tag(name: str) -> str:
        return f"{{{NAMESPACE}}}{name}"

    def decimal(value: float) -> str:
        # GPX uses xsd:decimal: no exponent notation or rounding up to +180.
        return format(Decimal(str(value)), "f")

    root = ET.Element(tag("gpx"), version="1.1", creator="boboji timeline_to_fog.py")
    track = ET.SubElement(root, tag("trk"))
    ET.SubElement(track, tag("name")).text = "Google Maps Timeline"
    for points in conversion.tracks:
        segment = ET.SubElement(track, tag("trkseg"))
        # A zero-length pair represents an isolated location as a track, without
        # turning a visit or an activity endpoint into a guessed route.
        output_points = points if len(points) > 1 else points * 2
        for point in output_points:
            node = ET.SubElement(
                segment,
                tag("trkpt"),
                lat=decimal(point.latitude),
                lon=decimal(point.longitude),
            )
            if point.elevation is not None:
                ET.SubElement(node, tag("ele")).text = decimal(point.elevation)
            if point.time is not None:
                ET.SubElement(node, tag("time")).text = point.time.isoformat().replace("+00:00", "Z")
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"
