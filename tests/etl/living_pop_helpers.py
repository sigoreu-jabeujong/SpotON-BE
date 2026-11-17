import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path

import shapefile
from pyproj import CRS

from etl.living_pop.data import SOURCES
from etl.living_pop.fields import FIELDS
from etl.living_pop.source import PAD


def make_grid(path: Path, *, crs=5179, width=250, duplicate=False):
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    with shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=5, encoding="utf-8") as writer:
        writer.field("CELL_ID", "C", 80)
        writer.field("CELL_X", "N", 18, 0)
        writer.field("CELL_Y", "N", 18, 0)
        writer.field("GID", "C", 14)
        for i in range(2):
            x, y = 950000 + i * 250, 1950000
            writer.poly(
                [
                    [
                        (x - width / 2, y - 125),
                        (x - width / 2, y + 125),
                        (x + width / 2, y + 125),
                        (x + width / 2, y - 125),
                        (x - width / 2, y - 125),
                    ]
                ]
            )
            writer.record(f"가가{0 if duplicate else i:08d}", x, y, f"synthetic-{i}")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("cells/", b"")
        for ext, data in (
            (".shp", shp.getvalue()),
            (".shx", shx.getvalue()),
            (".dbf", dbf.getvalue()),
            (".cpg", b"UTF-8"),
            (".prj", CRS.from_epsg(crs).to_wkt().encode()),
        ):
            z.writestr("cells/cells" + ext, data)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_rows(kind):
    rows = []
    for hour in range(24):
        for admin in ("11110530", "11110540"):
            row = ["20261107", f"{hour:02d}", admin + " " * 5, "가가00000000", "12.34"]
            row += ["*"] * (len(FIELDS[kind]) - 5) + [""] * PAD[kind]
            rows.append(row)
    rows[0][4] = "*"
    rows[1][4] = ""
    rows[2][4] = "0.00"
    if kind == "local":
        for hour in range(24):
            rows.append(
                ["20261107", f"{hour:02d}", "11110530" + " " * 5, "가가99999999", "*"]
                + ["*"] * (len(FIELDS[kind]) - 5)
                + [""] * PAD[kind]
            )
    return rows


def write_source(path, kind, rows=None, *, headers=None, encoding="cp949"):
    content = io.StringIO(newline="")
    writer = csv.writer(content)
    writer.writerow(headers or FIELDS[kind])
    writer.writerows(source_rows(kind) if rows is None else rows)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("synthetic.csv", content.getvalue().encode(encoding))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_manifest(root: Path, *, patches=None, grid_kwargs=None):
    root.mkdir(parents=True, exist_ok=True)
    grid = root / "grid.zip"
    sha = make_grid(grid, **(grid_kwargs or {}))
    manifest = {
        "observation_date": "2026-11-07",
        "grid": {"path": str(grid), "sha256": sha},
        "sources": {},
    }
    for kind in SOURCES:
        p = root / (kind + ".zip")
        rows = source_rows(kind)
        if patches and kind in patches:
            rows = patches[kind](rows)
        sha = write_source(p, kind, rows)
        manifest["sources"][kind] = {"path": str(p), "sha256": sha, "file_date": "2026-11-11"}
    p = root / "manifest.json"
    p.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return p
