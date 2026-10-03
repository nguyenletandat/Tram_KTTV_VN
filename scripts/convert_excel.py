import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import geopandas as gpd
import pyproj
from shapely.geometry import Point

from convert_mapinfo import recover_cp1252_roundtrip, tcvn3_decode_batch, OUT, PROJECT_ROOT

ROOT = str(PROJECT_ROOT)


def fix_series(series):
    raw = [recover_cp1252_roundtrip(v) if isinstance(v, str) else None for v in series]
    idx_with_text = [i for i, v in enumerate(raw) if v is not None]
    to_decode = [raw[i] for i in idx_with_text]
    decoded = tcvn3_decode_batch(to_decode)
    out = list(series)
    for i, d in zip(idx_with_text, decoded):
        out[i] = d
    return out


def dms_space_to_decimal(raw):
    """'080 14\u2019' -> 8 + 14/60 ; '106036\u2019' -> 106 + 36/60.
    Minutes are always the last 3 digits (zero-padded, e.g. '014' = 14');
    degree is whatever digits remain before that (2 digits for latitude
    8-23 deg, 3 digits for longitude 100-111 deg). Verified against known
    station coordinates (Con Dao 8.68N, Truong Sa 111.92E, Bac Lieu 105.72E)."""
    if not isinstance(raw, str):
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 4:
        return None
    deg = int(digits[:-3])
    minute = int(digits[-3:])
    return deg + minute / 60.0


def dms_full_to_decimal(raw):
    """'103o10\'07\"' -> 103 + 10/60 + 7/3600."""
    if not isinstance(raw, str):
        return None
    m = re.match(r"\s*(\d+)[oO\u00b0]\s*(\d+)['\u2019]\s*(\d+)", raw)
    if not m:
        return None
    deg, minute, sec = (int(x) for x in m.groups())
    return deg + minute / 60.0 + sec / 3600.0


def to_float_vn(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------
# E1: "khi tuong" + "TRICH" sheets -> meteorological stations (DMS, no seconds)
# ---------------------------------------------------------------------
def build_khituong_dms():
    xls = pd.ExcelFile(f"{ROOT}/danhsach cac tram KTTV.xls")
    df1 = xls.parse("khi tuong", header=None, skiprows=4,
                     names=["Ma_Clicom", "Ten_tram", "Lat_raw", "Lon_raw", "Docao"])
    df2 = xls.parse("TRICH", header=None,
                     names=["Ma_Clicom", "Ten_tram", "Lat_raw", "Lon_raw", "Docao"])
    df = pd.concat([df1, df2], ignore_index=True)
    df = df.dropna(subset=["Lat_raw", "Lon_raw"])

    df["Ten_tram"] = fix_series(df["Ten_tram"])
    df["Lat"] = df["Lat_raw"].apply(dms_space_to_decimal)
    df["Lon"] = df["Lon_raw"].apply(dms_space_to_decimal)
    df["Docao"] = df["Docao"].apply(to_float_vn)
    df = df.dropna(subset=["Lat", "Lon"])

    geom = [Point(xy) for xy in zip(df["Lon"], df["Lat"])]
    gdf = gpd.GeoDataFrame(
        df[["Ma_Clicom", "Ten_tram", "Lat_raw", "Lon_raw", "Lat", "Lon", "Docao"]],
        geometry=geom, crs="EPSG:4326")
    outp = OUT / "Excel_KhiTuong" / "khituong_dms_clicom.shp"
    outp.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(outp, encoding="utf-8")
    print(f"wrote {outp} ({len(gdf)} features)")


# ---------------------------------------------------------------------
# E2: "thuy van" sheet -> hydrological stations (full DMS with seconds)
# ---------------------------------------------------------------------
def build_thuyvan_dms():
    xls = pd.ExcelFile(f"{ROOT}/danhsach cac tram KTTV.xls")
    df = xls.parse("thuy van", header=None, skiprows=3,
                    names=["TT", "Dai_tram", "Ma_so", "F_km2", "Hang", "Lon_raw", "Lat_raw",
                           "Song", "HT_song", "Nam_XD", "Ten_dia_phuong", "Yeu_to_do",
                           "Cong_trinh_do", "_extra"])
    df = df.drop(columns=["_extra"])
    # drop section-header rows ("I. tay bac", etc.) which have no coordinate
    df = df[df["Lon_raw"].apply(lambda v: isinstance(v, str))]

    for col in ["Dai_tram", "Song", "HT_song", "Ten_dia_phuong", "Yeu_to_do", "Cong_trinh_do"]:
        df[col] = fix_series(df[col])

    df["Lat"] = df["Lat_raw"].apply(dms_full_to_decimal)
    df["Lon"] = df["Lon_raw"].apply(dms_full_to_decimal)
    df["F_km2"] = df["F_km2"].apply(to_float_vn)
    df["Nam_XD"] = df["Nam_XD"].apply(to_float_vn)
    df = df.dropna(subset=["Lat", "Lon"])

    geom = [Point(xy) for xy in zip(df["Lon"], df["Lat"])]
    keep = ["TT", "Dai_tram", "Ma_so", "F_km2", "Hang", "Song", "HT_song", "Nam_XD",
            "Ten_dia_phuong", "Yeu_to_do", "Cong_trinh_do", "Lat", "Lon"]
    gdf = gpd.GeoDataFrame(df[keep], geometry=geom, crs="EPSG:4326")
    outp = OUT / "Excel_ThuyVan" / "thuyvan_dms_full.shp"
    outp.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(outp, encoding="utf-8")
    print(f"wrote {outp} ({len(gdf)} features)")


# ---------------------------------------------------------------------
# E3: "Ten tram thuy van_tram man" sheet -> southern stations, VN-2000/UTM48N
# ---------------------------------------------------------------------
def build_thuyvan_nam_utm():
    xls = pd.ExcelFile(f"{ROOT}/danh-sach-tram-KT-TV.xls")
    df = xls.parse("Tên tram thuy van_trạm mặn", header=None, skiprows=3,
                    names=["TT", "Ten_tram", "Ma_tram", "X", "Y", "Ten_song", "Ten_tinh"])
    df = df.dropna(subset=["X", "Y"])

    for col in ["Ten_tram", "Ten_song", "Ten_tinh"]:
        df[col] = fix_series(df[col])

    # The "Thuyvan" sheet's first 50 rows ("Trạm cơ bản" section) list the
    # same 50 stations in the same order and carry the data-availability
    # period per measured factor (water level / rainfall / discharge),
    # which "Tên tram thuy van_trạm mặn" does not. Join by row position
    # (verified: both list "Phú An" ... "Sông Đốc" in identical order).
    periods = xls.parse("Thuyvan", header=None).iloc[8:58, [7, 8, 9]]
    periods.columns = ["TG_MucNuoc", "TG_Mua", "TG_LuuLuong"]
    periods = periods.reset_index(drop=True)
    for col in periods.columns:
        periods[col] = fix_series(periods[col])
    df = df.reset_index(drop=True)
    df = pd.concat([df, periods], axis=1)

    transformer = pyproj.Transformer.from_crs("EPSG:3405", "EPSG:4326", always_xy=True)
    lon, lat = transformer.transform(df["X"].to_numpy(), df["Y"].to_numpy())
    geom = [Point(xy) for xy in zip(lon, lat)]

    gdf = gpd.GeoDataFrame(
        df[["TT", "Ten_tram", "Ma_tram", "Ten_song", "Ten_tinh", "X", "Y",
            "TG_MucNuoc", "TG_Mua", "TG_LuuLuong"]],
        geometry=geom, crs="EPSG:4326")
    outp = OUT / "Excel_ThuyVan" / "thuyvan_nam_utm48n.shp"
    outp.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(outp, encoding="utf-8")
    print(f"wrote {outp} ({len(gdf)} features) [source CRS assumed VN-2000/UTM48N, EPSG:3405; "
          f"data-availability periods joined from 'Thuyvan' sheet by row position]")


if __name__ == "__main__":
    build_khituong_dms()
    build_thuyvan_dms()
    build_thuyvan_nam_utm()
    print("DONE")
