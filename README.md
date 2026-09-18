# PrimeTime Collection Exporter — v1.0.0

Lấy timing trực tiếp từ `get_timing_paths` / `get_attribute`, xuất dữ liệu có cấu trúc để debug, so sánh và đưa vào Python/Tk/HTML. Không parse timing report.

**Chạy trong `pt_shell` đã load design và timing. `tclsh` độc lập không có database/API PrimeTime.**

1. Đọc `USER_GUIDE.html` hoặc `USER_GUIDE.md`.
2. Sửa `example_run.tcl`: context, scenario, revision, path group, số path, đơn vị và output directory mới.
3. Trong PrimeTime: `source /absolute/path/pt_collection_v1/example_run.tcl`.
4. Ngoài PrimeTime: `python3 timing_data.py validate /path/to/output`.

| File | Nơi sửa khi cần |
|---|---|
| `example_run.tcl`, `config.tcl` | Chọn path, số lượng, threshold, đơn vị |
| `attributes.tcl` | Tên và kiểu attribute theo phiên bản PrimeTime |
| `adapter.tcl` | Lệnh native/API PrimeTime |
| `collect.tcl` | Đổi collection thành record |
| `calculate.tcl` | Công thức và điều kiện được phép tính |
| `writers.tcl`, `common.tcl` | Schema, JSON/CSV, encoding |
| `run.tcl` | Luồng điều khiển, validation, output hoàn tất/partial |
| `timing_data.py` | Reader Python 3.6+, summary, compare cùng schema |
| `tests/` | Collection mô phỏng và regression tests |
| `demo_export/` | Dữ liệu tổng hợp để thử reader; **không phải output PrimeTime thật** |

V1 xuất dữ liệu phía PrimeTime. Innovus cần adapter xuất cùng schema và quy ước metric; bộ này chưa gọi Innovus. `timing_data.py compare` dùng để kiểm tra cơ chế ghép/so sánh dữ liệu cùng schema, không nhận report text Innovus.

Kiểm thử: `python3 -m unittest discover -s tests -v`. Tests dùng `tkinter.Tcl()` không mở cửa sổ. Có thể chạy smoke test bằng `tclsh tests/run_mock.tcl` nếu máy có Tcl 8.5+.

Xem `TEST_RESULTS.md` để phân biệt phần đã kiểm thử với phần cần xác nhận trên PrimeTime thật.
