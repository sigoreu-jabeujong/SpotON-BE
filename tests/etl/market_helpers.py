import hashlib
import io
import zipfile
from pathlib import Path
from typing import Any

import shapefile
from pyproj import CRS

from etl.market_areas.archive import GU_CODES, MARKET_TYPES


def make_archive(
    path: Path,
    *,
    patches: dict[int, dict[str, Any]] | None = None,
    shapes: dict[int, list[list[list[float]]]] | None = None,
    replacements: dict[str, bytes] | None = None,
    extra: tuple[str, bytes] | None = None,
    crs: int = 5181,
) -> str:
    """Synthetic 25-gu source; no actual market or private point records."""
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    with shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=5, encoding="utf-8") as w:
        for name, width in [
            ("TRDAR_SE_C", 1),
            ("TRDAR_SE_1", 12),
            ("TRDAR_CD", 10),
            ("TRDAR_CD_N", 200),
            ("SIGNGU_CD", 5),
        ]:
            w.field(name, "C", width)
        w.field("RELM_AR", "N", 18, 2)
        for i, gu in enumerate(sorted(GU_CODES)):
            kind = list(MARKET_TYPES)[i % 4]
            row = dict(
                TRDAR_SE_C=kind,
                TRDAR_SE_1=MARKET_TYPES[kind][0],
                TRDAR_CD=str(3110000 + i),
                TRDAR_CD_N="source-name-private-canary",
                SIGNGU_CD=gu,
                RELM_AR=100,
            )
            row.update((patches or {}).get(i, {}))
            x, y = 200000 + i * 30, 450000
            rings = (shapes or {}).get(
                i, [[[x, y], [x, y + 10], [x + 10, y + 10], [x + 10, y], [x, y]]]
            )
            w.poly(rings)
            w.record(
                *(
                    row[name]
                    for name in [
                        "TRDAR_SE_C",
                        "TRDAR_SE_1",
                        "TRDAR_CD",
                        "TRDAR_CD_N",
                        "SIGNGU_CD",
                        "RELM_AR",
                    ]
                )
            )
    contents = {
        ".shp": shp.getvalue(),
        ".shx": shx.getvalue(),
        ".dbf": dbf.getvalue(),
        ".prj": CRS.from_epsg(crs).to_wkt().encode(),
        ".cpg": b"UTF-8",
    }
    contents.update(replacements or {})
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for suffix, blob in contents.items():
            z.writestr("synthetic" + suffix, blob)
        if extra:
            z.writestr(*extra)
    return hashlib.sha256(path.read_bytes()).hexdigest()
