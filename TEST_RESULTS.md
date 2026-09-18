# Kết quả kiểm thử v1.0.0

Ngày thực hiện: 2026-09-17.

**23 regression tests đạt.** Runtime: Python 3.12.14, Tcl 9.0.4 qua `tkinter.Tcl()` không mở GUI. Code Tcl dùng các cấu trúc của Tcl 8.5+; chưa chạy trực tiếp trên interpreter 8.5/8.6 của PrimeTime. `timing_data.py` dùng standard library và đã kiểm tra cú pháp tương thích Python 3.6; chưa chạy trên runtime Python 3.6.

Chạy lại từ thư mục bộ script:

```bash
python3 -m unittest discover -s tests -v
```

Mock dùng collection handles riêng, không dùng danh sách tên pin để giả làm native collection. Điều này giúp bắt lỗi lẫn collection handle với Tcl list, nhưng **không chứng minh API của một bản PrimeTime thực tế được hỗ trợ**.

| Nhóm | Điều đã kiểm tra |
|---|---|
| Tính timing | Launch/capture network span, CK→Q, Q→endpoint, CK→endpoint, edge separation, setup/hold slack sign |
| Mốc arrival | Data points dùng mốc 0; clock points dùng mốc 10/20; kết quả network/data vẫn đúng vì lấy hiệu trong cùng chuỗi |
| SI | Phân đoạn, không đếm launch CK lần nữa trong data, missing ≠ zero, SI âm giữ dấu, partial coverage |
| Clock / loại path | Nhiều clock path phù hợp, clock collection thiếu, ideal clock, generated-clock source, latch, Q-only path |
| Selection | Group patterns chồng nhau, limit theo group, nworst, no-match group, cutoff không có path |
| Đơn vị | ps → ns, ngưỡng slack được đổi ngược sang đơn vị native khi query |
| Serialization | JSON và CSV-only, dấu phẩy/quote/backslash/bracket/newline/Unicode; null, boolean và numeric round trip |
| Debug / mở rộng | NaN/Inf không xuất thành số JSON, provenance invalid/unavailable, thêm attribute không sửa writer |
| Control | Config sai, output đã tồn tại, slack mismatch, giữ partial output và error context |
| Reader / compare | Manifest completion, context khác, identity thiếu, topology khác, khóa trùng không ghép tùy ý, native sign giữa hai tool không giả định tương đương, float edge noise |

Dataset `demo_export/` được tạo từ mock, không từ PrimeTime thật. Những giá trị kỳ vọng:

| Metric | Giá trị (ns) |
|---|---:|
| `tlaunch_ns` | 0.300 |
| `tcapture_ns` | 0.330 |
| `tck2q_ns` | 0.095 |
| `tdata_ns` | 2.172 |
| `tdata_plus_ck2q_ns` | 2.267 |
| `phase_shift_ns` | 2.000 |
| `slack_ns` | -0.215 |
| `si_data_complete_sum_ns` | 0.090 |
| `si_launch_complete_sum_ns` | 0.060 |
| `si_capture_complete_sum_ns` | 0.020 |

Số double có thể hiển thị sai khác rất nhỏ ở những chữ số cuối; giữ precision khi export, làm tròn ở tầng hiển thị.

Chưa xác nhận trong môi trường có license: attribute availability trên release của bạn, các tùy chọn `get_timing_paths`, timing semantics với PBA/POCV/latch/special checks, và dữ liệu do Innovus xuất. Hướng dẫn chạy thử 5 path và tra local man pages nằm trong User Guide.
