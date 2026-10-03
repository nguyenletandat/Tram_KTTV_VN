# Trạm KTTV Việt Nam

WebGIS xem vị trí các trạm quan trắc khí tượng, thuỷ văn và chất lượng nước
trên cả nước, số hoá từ bản đồ MapInfo và danh sách trạm thập niên 2000.

**Xem bản đồ:** bật GitHub Pages cho repo này (Settings → Pages → Source:
Deploy from branch → `main` / `docs`) để có link dạng
`https://<tài-khoản>.github.io/<tên-repo>/`.

## Cấu trúc

```
docs/      WebGIS tĩnh (Leaflet, không phụ thuộc dịch vụ cần API key) +
           dữ liệu trạm dạng GeoJSON rút gọn, dùng để hiển thị bản đồ.
scripts/   Script Python tạo ra dữ liệu GeoJSON trong docs/ từ dữ liệu
           nguồn (MapInfo .TAB + Excel). Dữ liệu nguồn và shapefile đầy đủ
           không được publish trong repo này.
```

## Những điểm cần biết về dữ liệu

- Văn bản tiếng Việt trong nguồn dùng font cũ TCVN3/ABC nhưng bị khai sai
  charset trong file MapInfo; scripts giải mã lại đúng bằng bảng TCVN-5712
  (GNU libiconv).
- Lớp "trạm thuỷ văn" trong dữ liệu gốc có hai lỗi độc lập: (1) ~64% tên
  trạm tiếng Việt bị hỏng ký tự ngay trong file nguồn — đã khôi phục được
  một phần bằng cách đối chiếu với lớp dữ liệu sạch hơn, phần còn lại được
  đánh dấu rõ trên bản đồ; (2) hình học điểm trong file `.MAP` bị làm tròn
  về độ nguyên (sai lệch hàng chục km) cho toàn bộ 361 trạm — đã khắc phục
  bằng cách dựng lại toạ độ từ cột thuộc tính X/Y gốc (chính xác đầy đủ,
  không bị ảnh hưởng bởi lỗi trên).
- Lớp trạm thuỷ văn miền Nam dùng hệ toạ độ VN-2000/UTM zone 48N (suy luận
  từ việc đối chiếu một điểm đã biết vị trí thực tế).

## Tái tạo dữ liệu cho docs/

```bash
pip install -r scripts/requirements.txt
python scripts/convert_mapinfo.py
python scripts/convert_excel.py
```

Yêu cầu GDAL (`ogr2ogr`, có sẵn trong QGIS/OSGeo4W) và GNU libiconv hỗ trợ
`TCVN-5712` (có sẵn trong Git for Windows). Sau khi script tạo lại
`shp_output/`, cần export các lớp cần thiết sang GeoJSON và đặt vào
`docs/` theo đúng tên file mà `docs/index.html` tham chiếu.
