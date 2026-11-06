"""Keep README chips local, accessible and visually consistent."""

import re
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
SVG = "{http://www.w3.org/2000/svg}"


def test_readme_chip_standard():
    readme = (ROOT / "README.md").read_text()
    chips = re.findall(r"\[!\[([^\]]+)\]\((docs/badges/[^)]+)\)\]\(([^)]+)\)", readme)
    assert [Path(path).name for _, path, _ in chips] == [
        "ci.svg",
        "compatibility.svg",
        "license.svg",
        "distribution.svg",
    ]
    assert len(re.findall(r"\[!\[", readme)) == 4
    colors = ["#64748b", "#0369a1", "#2563eb", "#047857"]
    for (alt, path, link), color in zip(chips, colors, strict=True):
        image = ElementTree.parse(ROOT / path).getroot()
        assert image.tag == SVG + "svg"
        assert image.attrib["height"] == "20"
        assert image.attrib["role"] == "img"
        assert image.attrib["aria-label"] == alt
        assert image.findtext(SVG + "title") == alt
        clip = image.find(SVG + "clipPath/" + SVG + "rect")
        assert clip is not None and clip.attrib["rx"] == "3"
        rects = image.findall(SVG + "g/" + SVG + "rect")
        assert rects[0].attrib["fill"] == "#555"
        assert rects[1].attrib["fill"] == color
        assert all(rect.attrib["height"] == "20" for rect in rects)
        label_width = float(rects[0].attrib["width"])
        value_width = float(rects[1].attrib["width"])
        assert float(rects[1].attrib["x"]) == label_width
        assert float(image.attrib["width"]) == label_width + value_width
        text_group = image.findall(SVG + "g")[1]
        assert text_group.attrib["font-family"] == "DejaVu Sans,Verdana,sans-serif"
        assert text_group.attrib["font-size"] == "11"
        assert text_group.attrib["fill"] == "#fff"
        assert text_group.attrib["text-anchor"] == "middle"
        text = image.findall(SVG + "g/" + SVG + "text")
        assert len(text) == 2
        assert ": ".join(node.text or "" for node in text) == alt
        assert all(node.attrib["y"] == "14" for node in text)
        for node, start, width in (
            (text[0], 0, label_width),
            (text[1], label_width, value_width),
        ):
            assert float(node.attrib["x"]) == start + width / 2
            assert float(node.attrib["textLength"]) == width - 12
            assert node.attrib["lengthAdjust"] == "spacingAndGlyphs"
        assert not any(
            node.tag.removeprefix(SVG)
            in {"script", "image", "filter", "linearGradient"}
            or any(key.startswith("on") or "href" in key for key in node.attrib)
            for node in image.iter()
        )
        if link.startswith("#"):
            headings = re.findall(r"^#+ (.+)$", readme, re.MULTILINE)
            assert link[1:] in [
                heading.lower().replace(" ", "-") for heading in headings
            ]
        elif not link.startswith("https://"):
            assert (ROOT / link).is_file()
    assert [alt for alt, _, _ in chips] == [
        "CI: workflow",
        "HA tested: 2026.11.0",
        "License: MIT",
        "Distribution: HACS custom",
    ]
    workflow = "https://github.com/ColeMundus/ha-clash-royale/actions/workflows/ci.yml"
    assert [link for _, _, link in chips] == [
        workflow,
        workflow,
        "LICENSE",
        "#installation",
    ]
    assert (ROOT / ".github/workflows/ci.yml").is_file()
    assert {path.name for path in (ROOT / "docs/badges").glob("*.svg")} == {
        "ci.svg",
        "compatibility.svg",
        "license.svg",
        "distribution.svg",
    }
