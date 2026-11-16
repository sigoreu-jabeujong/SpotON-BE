import csv
import hashlib
import io
import zipfile

import shapefile
from pyproj import CRS

from etl.admin_population.source import HEADERS


def population_zip(
    path,
    *,
    patches=None,
    duplicate=False,
    member=None,
    delimiter=";",
    day="20261031",
):
    output = io.StringIO(newline="")
    csv.writer(output).writerow(HEADERS)
    writer = csv.writer(output, delimiter=delimiter)
    rows = []
    for admin in ("11110530", "11110540"):
        for hour in range(24):
            row = [day, f"{hour:02}", admin + "     ", "12.34", *("0" for _ in HEADERS[4:])]
            row[3] = (patches or {}).get((admin, hour), row[3])
            rows.append(row)
    writer.writerows(rows)
    if duplicate:
        writer.writerow(rows[0])
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            member or f"250_LOCAL_RESD_ADMDONG_{day}.csv", output.getvalue().encode("cp949")
        )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def boundary_zip(path, *, code="11110530", cpg=b"UTF-8", crs=5181):
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    with shapefile.Writer(shp=shp, shx=shx, dbf=dbf, encoding="utf-8", shapeType=5) as writer:
        writer.field("ADSTRD_CD", "C", 8)
        writer.field("ADSTRD_NM", "C", 30)
        for field in ("XCNTS_VALU", "YDNTS_VALU", "RELM_AR"):
            writer.field(field, "N", 18, 0)
        writer.poly(
            [
                [
                    [200000, 450000],
                    [200000, 450010],
                    [200010, 450010],
                    [200010, 450000],
                    [200000, 450000],
                ]
            ]
        )
        writer.record(code, "합성검사동", 200005, 450005, 100)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for ext, data in {
            ".shp": shp.getvalue(),
            ".shx": shx.getvalue(),
            ".dbf": dbf.getvalue(),
            ".prj": CRS.from_epsg(crs).to_wkt().encode(),
            ".cpg": cpg,
        }.items():
            archive.writestr("synthetic" + ext, data)
    return hashlib.sha256(path.read_bytes()).hexdigest()
