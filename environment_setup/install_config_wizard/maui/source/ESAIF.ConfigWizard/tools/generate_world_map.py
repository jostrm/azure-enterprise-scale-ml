"""Build the offline mission-control basemap from Natural Earth's public-domain GeoJSON."""

import argparse
import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET


WIDTH = 1440
HEIGHT = 580
NORTH = 85
SOUTH = -60
SOURCE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_110m_admin_0_countries.geojson"
)


def project(longitude, latitude):
    return (longitude + 180) * WIDTH / 360, (NORTH - latitude) * HEIGHT / (NORTH - SOUTH)


def generate(source, destination):
    raw = source.read_bytes()
    countries = json.loads(raw)["features"]
    svg = ET.Element("svg", {
        "xmlns": "http://www.w3.org/2000/svg",
        "width": str(WIDTH), "height": str(HEIGHT),
        "viewBox": f"0 0 {WIDTH} {HEIGHT}",
    })
    ET.SubElement(svg, "title").text = "Azure regional operations - world map"
    ET.SubElement(svg, "desc").text = (
        "Made with Natural Earth. Public-domain 1:110m country boundaries. "
        "Equirectangular projection: longitude -180..180, latitude 85..-60. "
        "Approximate geography; boundaries do not imply endorsement. "
        f"Source: {SOURCE_URL}; SHA256: {hashlib.sha256(raw).hexdigest()}."
    )
    defs = ET.SubElement(svg, "defs")
    ocean = ET.SubElement(defs, "radialGradient", {"id": "ocean", "cx": ".5", "cy": ".4", "r": ".75"})
    ET.SubElement(ocean, "stop", {"offset": "0", "stop-color": "#121D34"})
    ET.SubElement(ocean, "stop", {"offset": "1", "stop-color": "#080E1B"})
    land = ET.SubElement(defs, "linearGradient", {"id": "land", "x2": "0", "y2": "1"})
    ET.SubElement(land, "stop", {"offset": "0", "stop-color": "#263450"})
    ET.SubElement(land, "stop", {"offset": "1", "stop-color": "#17273C"})
    clip = ET.SubElement(defs, "clipPath", {"id": "viewport"})
    ET.SubElement(clip, "rect", {"width": str(WIDTH), "height": str(HEIGHT)})
    ET.SubElement(svg, "rect", {"width": str(WIDTH), "height": str(HEIGHT), "fill": "url(#ocean)"})
    graticule = ET.SubElement(svg, "g", {
        "id": "graticule", "stroke": "#355477", "stroke-opacity": ".24",
        "stroke-width": ".7", "fill": "none",
    })
    for longitude in range(-180, 181, 15):
        x, _ = project(longitude, 0)
        ET.SubElement(graticule, "path", {"d": f"M{x:.2f} 0V{HEIGHT}"})
    for latitude in range(-60, 86, 15):
        _, y = project(0, latitude)
        ET.SubElement(graticule, "path", {"d": f"M0 {y:.2f}H{WIDTH}"})
    outlines = ET.SubElement(svg, "g", {
        "id": "countries", "fill": "url(#land)", "stroke": "#536383",
        "stroke-width": ".7", "stroke-linejoin": "round",
        "clip-path": "url(#viewport)", "fill-rule": "evenodd",
    })
    for feature in countries:
        geometry = feature["geometry"]
        polygons = (
            [geometry["coordinates"]] if geometry["type"] == "Polygon"
            else geometry["coordinates"]
        )
        rings = []
        for polygon in polygons:
            for ring in polygon:
                if max(point[1] for point in ring) < SOUTH:
                    continue
                points = [project(*point[:2]) for point in ring]
                rings.append(
                    "M" + "L".join(f"{x:.2f},{y:.2f}" for x, y in points) + "Z"
                )
        if rings:
            ET.SubElement(outlines, "path", {
                "data-country": feature["properties"]["ADMIN"],
                "d": "".join(rings),
            })
    _, equator = project(0, 0)
    ET.SubElement(svg, "path", {
        "d": f"M0 {equator:.2f}H{WIDTH}",
        "stroke": "#58CEE5", "stroke-opacity": ".26",
        "stroke-width": ".8", "stroke-dasharray": "5 7", "fill": "none",
    })
    ticks = ET.SubElement(svg, "g", {"fill": "#7893B6", "font-size": "9", "font-family": "monospace"})
    for longitude in range(-150, 180, 30):
        x, _ = project(longitude, 0)
        label = f"{abs(longitude)}{'W' if longitude < 0 else 'E' if longitude else ''}"
        ET.SubElement(ticks, "text", {"x": str(x), "y": "14", "text-anchor": "middle"}).text = label
    ET.SubElement(svg, "path", {
        "d": f"M0 25V0H25 M{WIDTH-25} 0H{WIDTH}V25 "
             f"M0 {HEIGHT-25}V{HEIGHT}H25 M{WIDTH-25} {HEIGHT}H{WIDTH}V{HEIGHT-25}",
        "fill": "none", "stroke": "#56D7E8", "stroke-opacity": ".7", "stroke-width": "2",
    })
    ET.indent(svg)
    destination.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(svg).write(destination, encoding="utf-8", xml_declaration=True)
    print(f"Generated {len(outlines)} country outlines in {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Natural Earth ne_110m_admin_0_countries.geojson")
    parser.add_argument("destination", type=Path, help="Output world_map.svg")
    args = parser.parse_args()
    generate(args.source, args.destination)
