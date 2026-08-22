# Runbook vận hành

## Trạng thái bình thường

Một máy sẵn sàng calibration khi:

- Klipper `ready`, XYZ đã home và không printing/paused;
- toolchanger initialized và reference tool đang hoạt động cho setup;
- `TV_STATUS` thấy host service đúng version;
- camera setup/switch setup phù hợp với `MODE`;
- switch đang open trước probe;
- đường nâng Z, đường XY và fixture không có vật cản;
- nozzle sạch, camera đủ nhìn và không có nhựa rỉ che ảnh.

ToolVision không thay thế kiểm tra cơ khí của người vận hành.

## Cài đặt lần đầu

1. Backup config máy và ghi lại commit Klipper/Moonraker/toolchanger.
2. Cài/kiểm tra `tools_calibrate.py`, nhưng không bật section
   `[tools_calibrate]` cùng `[tool_vision]`.
3. Clone release/nhánh đã phê duyệt và chạy `./install.sh` trong phiên terminal
   có sudo.
4. Thêm `[include Tool-Vision/tool_vision.cfg]` vào `printer.cfg`.
5. Restart và chạy `TV_STATUS`.
6. Kiểm tra API health, Klipper ready và updater `tool-vision` xuất hiện trong
   Mainsail.

Không cài trong khi đang print. Installer hiện chưa transactional hoàn toàn;
fresh install/upgrade cần theo checklist và giữ backup cho đến khi health pass.

## Cập nhật bình thường

1. Đọc changelog/release evidence; không bấm “Update all” nếu chưa biết release
   có đổi motion, schema hoặc dependency.
2. Đảm bảo máy idle, heater an toàn và không có calibration đang chạy.
3. Tạo backup config/state/result nếu release đổi schema/setup/measurement.
4. Mở **Machine → Update Manager → tool-vision → Update**.
5. Chờ Moonraker hoàn tất restart `tool-vision` và Klipper.
6. Chạy `TV_STATUS`; xác nhận version, service online và station vẫn đúng.
7. Với release ảnh hưởng đo, chạy validation/HIL nhỏ trước calibration đầy đủ.

Không chạy `git pull` trực tiếp cho cập nhật bình thường. Repository runtime phải
sạch để Moonraker quản lý đúng.

## Setup camera

Pre-check:

- reference tool đúng và offset baseline zero theo giới hạn hiện tại;
- nozzle sạch, gần tâm ảnh và có khoảng trống ít nhất cho vòng ±0,5 mm;
- station không sát giới hạn máy; tính cả configured offset của mọi tool;
- Z hiện tại cho ảnh đủ rõ và chuyển động ngang không chạm lens/fixture;
- camera stream không bị freeze.

Chạy:

```gcode
TV_SETUP_CAMERA
```

Chỉ chấp nhận khi có thông báo vị trí, sharpness, transform RMS và số sample.
Sau setup, backup state mới. Nếu setup fail, không lặp vô hạn; xem preview/log,
kiểm tra camera/focus/light/nozzle rồi mới thử lại.

## Setup switch

Pre-check:

- khai báo đúng `pin`, kiểm tra điện/polarity bằng `QUERY_ENDSTOPS`;
- reference tool đang gắn, switch open;
- nozzle thẳng trên mặt switch, cách trigger dưới 10 mm;
- station đủ xa giới hạn cho configured offset của mọi tool;
- đường probe thẳng không có clamp/vật cản.

Chạy:

```gcode
TV_SETUP_SWITCH
```

Setup có thể chạy lại và ghi đè station sau khi mọi check thành công. Backup state
cũ trước khi dạy lại nếu station cũ còn giá trị khôi phục.

## Calibration

1. Backup offset sản xuất hiện dùng và latest ToolVision result.
2. Home, kiểm tra fixture/nozzle/camera/switch.
3. Chọn mode nhỏ nhất cần thiết.
4. Chạy calibration và không can thiệp jog/toolchange song song.

```gcode
TV_CALIBRATE MODE=XY
TV_CALIBRATE MODE=Z
TV_CALIBRATE MODE=XYZ
```

Mặc định hệ thống dùng 150 °C, đợi từng active tool rồi tắt target mọi tool ở
cuối success/failure bình thường. `TEMP=0` là advanced cold run, không phải cách
bỏ qua kiểm tra heater.

Sau run:

- xác nhận heater target đều 0;
- xác nhận tool cuối/original tool đúng kỳ vọng;
- chạy `TV_REPORT` và lưu result;
- lặp ít nhất ba lần trong cùng điều kiện để phát hiện độ phân tán;
- không áp offset nếu result không lặp hoặc khác đáng kể baseline;
- xác nhận bằng phương pháp độc lập/print validation trước khi dùng sản xuất.

## Kiểm tra health

Trên host máy in:

```bash
systemctl is-active tool-vision klipper moonraker
curl --fail --silent http://127.0.0.1:8085/api/v2/health
journalctl -u tool-vision -n 100 --no-pager
```

Trong Mainsail:

```gcode
TV_STATUS
```

Không mở port 8085 trực tiếp ra LAN/Internet; service mặc định không có auth.

## Phân loại sự cố

### Heater không về 0 hoặc có mùi/nhiệt bất thường

1. Dừng thao tác; dùng `TURN_OFF_HEATERS` nếu Klipper còn nhận lệnh.
2. Nếu không còn điều khiển, dùng emergency procedure/phần cứng của máy.
3. Không chạy lại calibration trước khi xác nhận tất cả target/temperature an
   toàn.
4. Lưu log, result và incident report; xem R-004.

### Nozzle dừng thấp hoặc tool không khôi phục

1. Không jog XY khi chưa biết clearance.
2. Nếu Klipper ready và đường thẳng đứng an toàn, nâng Z bằng thao tác kiểm soát
   của máy.
3. Xác nhận active tool trước mọi command tiếp theo.
4. Lưu primary error và log; xem R-003.

### Camera timeout/offline/freeze

1. Không lặp calibration liên tục.
2. Kiểm tra camera trong Moonraker/Crowsnest và snapshot có thực sự thay đổi.
3. Restart camera service trước, rồi `tool-vision` nếu cần.
4. Nếu resolution/rotation/focus/mount thay đổi, setup camera lại.

### Switch stuck/no trigger

1. Nâng nozzle và kiểm tra `QUERY_ENDSTOPS`.
2. Kiểm tra wiring, invert/pull-up và mặt switch.
3. Không tăng `max_distance` để “thử” khi chưa xác định nguyên nhân.
4. Dạy lại station nếu switch đã di chuyển.

### Update fail hoặc version lệch

1. Không chạy installer lặp nhiều lần khi chưa đọc lỗi.
2. Ghi version từ Mainsail updater, `/api/v2/health` và `TV_STATUS`.
3. Kiểm tra repository sạch, branch đúng, service/path/symlink nhất quán.
4. Dùng backup/rollback đã kiểm thử theo [`BACKUP_RESTORE.md`](BACKUP_RESTORE.md).

## Thu thập bằng chứng sự cố

Lưu:

- thời gian/timezone, lệnh đã chạy và phase lỗi;
- ToolVision/Klipper/Moonraker/toolchanger commit;
- `TV_STATUS`, host health, systemd status;
- log ToolVision/Klipper/Moonraker quanh sự cố;
- state/result và ảnh preview liên quan nếu không có credential/dữ liệu nhạy
  cảm;
- heater/tool/position cuối và hành động khẩn cấp đã làm.

Dùng [`templates/INCIDENT_REPORT.md`](templates/INCIDENT_REPORT.md). Không sửa
log gốc; tạo bản redacted để chia sẻ.
