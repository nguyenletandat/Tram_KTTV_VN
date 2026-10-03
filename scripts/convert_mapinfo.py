import glob
import json
import re
import shutil
import struct
import subprocess
from pathlib import Path

import geopandas as gpd
from shapely.geometry import shape, Point

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ROOT = PROJECT_ROOT / "Tramdo"
OUT = PROJECT_ROOT / "shp_output"


def _find_tool(name, glob_patterns):
    found = shutil.which(name)
    if found:
        return found
    for pattern in glob_patterns:
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            return matches[0]
    raise FileNotFoundError(
        f"Could not locate '{name}'. Install GDAL (QGIS bundles it) and/or "
        f"Git for Windows (ships GNU libiconv with TCVN-5712 support), or "
        f"edit this script to point OGR2OGR/ICONV at your install paths.")


OGR2OGR = _find_tool("ogr2ogr", [r"C:\Program Files\QGIS *\bin\ogr2ogr.exe",
                                  r"C:\OSGeo4W*\bin\ogr2ogr.exe"])
ICONV = _find_tool("iconv", [r"C:\Program Files\Git\usr\bin\iconv.exe"])


def tcvn3_decode_batch(values):
    """Decode a list of raw byte strings (TCVN3/ABC Vietnamese 8-bit font)
    to proper Unicode, using GNU libiconv's TCVN-5712 codec (verified against
    known station names: 'Dien Bien', 'Cam Le', 'Hoi An')."""
    if not values:
        return []
    blob = b"\n".join(values)
    proc = subprocess.run([ICONV, "-f", "TCVN-5712", "-t", "UTF-8"],
                           input=blob, capture_output=True, check=True)
    out = proc.stdout.decode("utf-8").split("\n")
    assert len(out) == len(values), f"{len(out)} != {len(values)}"
    return [v.strip() for v in out]


def read_dbf_raw(path):
    """Minimal dBASE III/IV reader returning raw bytes for Char fields and
    parsed values for Numeric fields, bypassing any charset recoding."""
    data = path.read_bytes()
    num_records = struct.unpack_from("<I", data, 4)[0]
    header_size = struct.unpack_from("<H", data, 8)[0]
    record_size = struct.unpack_from("<H", data, 10)[0]

    fields = []
    off = 32
    while data[off] != 0x0D:
        raw_name = data[off:off + 11]
        name = raw_name.split(b"\x00")[0].decode("ascii")
        ftype = chr(data[off + 11])
        flen = data[off + 16]
        fields.append((name, ftype, flen))
        off += 32

    records = []
    pos = header_size
    for i in range(num_records):
        rec = data[pos:pos + record_size]
        pos += record_size
        if rec[0:1] == b"*":
            continue  # deleted record
        row = {}
        fo = 1
        for name, ftype, flen in fields:
            raw = rec[fo:fo + flen]
            fo += flen
            if ftype == "C":
                row[name] = raw  # keep raw bytes for TCVN3 decode later
            else:
                txt = raw.decode("ascii", errors="strict").strip()
                row[name] = float(txt) if txt not in ("", ".") else None
        records.append(row)
    return fields, records


def fix_text_columns(records, fields, text_fields):
    for fname in text_fields:
        raw_values = [r[fname] for r in records]
        decoded = tcvn3_decode_batch(raw_values)
        for r, d in zip(records, decoded):
            r[fname] = d
    return records


def ogr_geojson(tab_path, with_style=False):
    out_json = tab_path.with_suffix(".conv.geojson")
    cmd = [OGR2OGR, "-f", "GeoJSON", "-t_srs", "EPSG:4326"]
    if with_style:
        layer_name = tab_path.stem
        cmd += ["-sql", f"SELECT *, OGR_STYLE FROM \"{layer_name}\""]
    cmd += [str(out_json), str(tab_path)]
    subprocess.run(cmd, check=True, capture_output=True)
    gj = json.loads(out_json.read_text(encoding="utf-8"))
    out_json.unlink()
    return gj["features"]


def recover_cp1252_roundtrip(value):
    """For layers where GDAL's CP1252->UTF-8 decode did not lose bytes,
    recover original bytes and re-decode as TCVN3."""
    if value is None or value == "":
        return value
    try:
        raw = value.encode("cp1252")
    except UnicodeEncodeError:
        raw = value.encode("cp1252", errors="replace")
    return raw


# ---------------------------------------------------------------------
# Layer definitions
# ---------------------------------------------------------------------
DBF_LAYERS = [
    dict(cat="Khituong", name="Tram-khituong", tab="Khituong/Tram-khituong.TAB",
         dbf="Khituong/Tram-khituong.DBF",
         text_fields=["MA_CLICOM", "TEN_TRAM", "TEN_TRAM_E", "THOIKYCOSO", "LOAITRAM"]),
    dict(cat="Khituong", name="Tram_khi_tuong", tab="Khituong/Tram_khi_tuong.TAB",
         dbf="Khituong/Tram_khi_tuong.DBF",
         text_fields=["MA_CLICOM", "TEN_TRAM", "TEN_TRAM_E", "THOIKYCOSO", "LOAITRAM"]),
    dict(cat="Thuyvan", name="Tramthuyvan", tab="Thuyvan/Tramthuyvan.TAB",
         dbf="Thuyvan/Tramthuyvan.dbf",
         text_fields=["STATION", "STATION_EN", "RIVER", "RIVER_SYST", "STA_LEVEL"]),
    dict(cat="Thuyvan", name="Tthuyvan", tab="Thuyvan/Tthuyvan.TAB",
         dbf="Thuyvan/Tthuyvan.DBF",
         text_fields=["STATION", "STATION_EN", "RIVER", "RIVER_SYST", "STA_LEVEL"]),
]

NATIVE_LAYERS = [
    dict(cat="Khituong", name="tram_kt", tab="Khituong/tram_kt.TAB",
         text_fields=["Station_vn", "Station_en"]),
    dict(cat="Thuyvan", name="tram_tv", tab="Thuyvan/tram_tv.TAB",
         text_fields=["Station_vn", "Station_en", "River_vn", "River_en"]),
    dict(cat="Chatluongnuoc", name="chatluongnuoc", tab="Chatluongnuoc/chatluongnuoc.TAB",
         text_fields=["Name_st", "Name_st_en"]),
    dict(cat="Chatluongnuoc", name="khuvuc_poly", tab="Chatluongnuoc/khuvuc_poly.tab",
         text_fields=["VUNG_"]),
]

# Non-spatial lookup table (no geometry) -> CSV, not SHP
NONSPATIAL = [
    dict(cat="Thuyvan", name="yeutodo", dbf="Thuyvan/yeutodo.DBF",
         text_fields=["STATION", "STATION_EN"]),
]

LABEL_LAYER = dict(cat="Chatluongnuoc", name="Name_st_en", tab="Chatluongnuoc/Name_st_en.TAB")


def write_shp(cat, name, records, geoms, crs="EPSG:4326"):
    outdir = OUT / cat
    outdir.mkdir(parents=True, exist_ok=True)
    gdf = gpd.GeoDataFrame(records, geometry=[shape(g) if g else None for g in geoms], crs=crs)
    out_path = outdir / f"{name}.shp"
    gdf.to_file(out_path, encoding="utf-8")
    print(f"wrote {out_path} ({len(gdf)} features)")


def process_dbf_layer(layer, clean_lookup=None):
    tab_path = ROOT / layer["tab"]
    dbf_path = ROOT / layer["dbf"]
    fields, records = read_dbf_raw(dbf_path)
    fix_text_columns(records, fields, layer["text_fields"])

    if clean_lookup is not None:
        n = patch_corrupted_station_names(records, clean_lookup)
        still_bad = sum(1 for r in records if not r["NAME_OK"])
        print(f"{layer['name']}: patched {n} corrupted station names from tram_tv, "
              f"{still_bad} remain unrecoverable (NAME_OK=False)")

    feats = ogr_geojson(tab_path)
    assert len(feats) == len(records), f"{layer['name']}: geom {len(feats)} vs attr {len(records)}"
    geoms = [f["geometry"] for f in feats]

    write_shp(layer["cat"], layer["name"], records, geoms)


def process_native_layer(layer):
    tab_path = ROOT / layer["tab"]
    feats = ogr_geojson(tab_path)
    geoms = [f["geometry"] for f in feats]
    records = [dict(f["properties"]) for f in feats]

    for fname in layer["text_fields"]:
        raw_values = [recover_cp1252_roundtrip(r.get(fname)) for r in records]
        decoded = tcvn3_decode_batch(raw_values)
        for r, d in zip(records, decoded):
            r[fname] = d

    write_shp(layer["cat"], layer["name"], records, geoms)


def process_nonspatial(layer, clean_lookup=None):
    dbf_path = ROOT / layer["dbf"]
    fields, records = read_dbf_raw(dbf_path)
    fix_text_columns(records, fields, layer["text_fields"])
    if clean_lookup is not None:
        n = patch_corrupted_station_names(records, clean_lookup)
        still_bad = sum(1 for r in records if not r["NAME_OK"])
        print(f"{layer['name']}: patched {n} corrupted station names from tram_tv, "
              f"{still_bad} remain unrecoverable (NAME_OK=False)")
    outdir = OUT / layer["cat"]
    outdir.mkdir(parents=True, exist_ok=True)
    import csv
    out_path = outdir / f"{layer['name']}.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(records[0].keys()))
        w.writeheader()
        w.writerows(records)
    print(f"wrote {out_path} ({len(records)} rows, no geometry)")


def process_label_layer(layer):
    tab_path = ROOT / layer["tab"]
    feats = ogr_geojson(tab_path, with_style=True)
    records = []
    geoms = []
    pat = re.compile(r'LABEL\(t:"([^"]*)"')
    for f in feats:
        style = f["properties"].get("OGR_STYLE", "") or ""
        m = pat.search(style)
        records.append({"name_en": m.group(1) if m else None})
        geoms.append(f["geometry"])
    write_shp(layer["cat"], layer["name"], records, geoms)


def build_clean_station_lookup():
    """tram_tv.TAB (NATIVE) decodes cleanly and overlaps with the corrupted
    Tramthuyvan.dbf/yeutodo.DBF Vietnamese station names. Use it to patch
    what we can; the rest of the corruption is unrecoverable (see README)."""
    feats = ogr_geojson(ROOT / "Thuyvan/tram_tv.TAB")
    raw_names = [recover_cp1252_roundtrip(f["properties"].get("Station_vn")) for f in feats]
    names = tcvn3_decode_batch(raw_names)
    lookup = {}
    for f, name in zip(feats, names):
        p = f["properties"]
        key = (round(p["X"], 3), round(p["Y"], 3))
        lookup[key] = name
    return lookup


def patch_corrupted_station_names(records, lookup):
    patched = 0
    for r in records:
        r["NAME_OK"] = "?" not in r["STATION"]
        if not r["NAME_OK"]:
            key = (round(r["X"], 3), round(r["Y"], 3))
            if key in lookup:
                r["STATION"] = lookup[key]
                r["NAME_OK"] = True
                patched += 1
    return patched


def main():
    clean_lookup = build_clean_station_lookup()

    tramthuyvan_records = None
    for layer in DBF_LAYERS:
        if layer["name"] == "Tramthuyvan":
            tab_path = ROOT / layer["tab"]
            dbf_path = ROOT / layer["dbf"]
            fields, records = read_dbf_raw(dbf_path)
            fix_text_columns(records, fields, layer["text_fields"])
            n = patch_corrupted_station_names(records, clean_lookup)
            still_bad = sum(1 for r in records if not r["NAME_OK"])
            print(f"{layer['name']}: patched {n} corrupted station names from tram_tv, "
                  f"{still_bad} remain unrecoverable (NAME_OK=False)")
            feats = ogr_geojson(tab_path)
            assert len(feats) == len(records)
            # The .MAP geometry for this table is corrupted: every single
            # point is truncated to whole-degree coordinates (verified: 361/361
            # records), stacking dozens of unrelated stations on top of each
            # other. The DBF's own X/Y attribute columns carry the real,
            # full-precision coordinates (verified: all 361 are non-integer),
            # so rebuild the geometry from those instead of trusting the .MAP.
            geoms = [{"type": "Point", "coordinates": [r["X"], r["Y"]]} for r in records]
            write_shp(layer["cat"], layer["name"], records, geoms)
            tramthuyvan_records = records
        else:
            process_dbf_layer(layer)

    for layer in NATIVE_LAYERS:
        process_native_layer(layer)

    for layer in NONSPATIAL:
        if layer["name"] == "yeutodo" and tramthuyvan_records is not None:
            fields, records = read_dbf_raw(ROOT / layer["dbf"])
            fix_text_columns(records, fields, layer["text_fields"])
            for r, patched in zip(records, tramthuyvan_records):
                r["STATION"] = patched["STATION"]
                r["NAME_OK"] = patched["NAME_OK"]
            outdir = OUT / layer["cat"]
            outdir.mkdir(parents=True, exist_ok=True)
            import csv
            out_path = outdir / f"{layer['name']}.csv"
            with open(out_path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(records[0].keys()))
                w.writeheader()
                w.writerows(records)
            print(f"wrote {out_path} ({len(records)} rows, no geometry, STATION patched positionally from Tramthuyvan)")
        else:
            process_nonspatial(layer)

    process_label_layer(LABEL_LAYER)
    print("DONE")


if __name__ == "__main__":
    main()
