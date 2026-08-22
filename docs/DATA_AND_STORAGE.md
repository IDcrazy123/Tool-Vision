# Dữ liệu và lưu trữ

## Phân loại

| Dữ liệu | Mặc định | Chủ sở hữu | Tái tạo được? | Backup |
|---|---|---|---|---|
| Git runtime | `~/Tool-Vision` | Git/Moonraker | Có | release tag + local bundle |
| Editable config | `~/printer_data/config/Printer-Setup/tool_vision.cfg` | người dùng | Không | bắt buộc |
| Learned state | `~/printer_data/config/Printer-Setup/tool_vision_state.json` | ToolVision | Có nhưng tốn setup/HIL | bắt buộc |
| Latest result | `~/printer_data/config/Printer-Setup/tool_vision_results.json` | ToolVision | Có nhưng không tái tạo đúng điều kiện cũ | bắt buộc trước apply |
| Host log | `~/printer_data/logs/tool-vision/tool-vision.log` | service | Có thể bỏ | theo incident/retention |
| Venv | `~/tool-vision-env` | pip/Moonraker | Có | không backup bình thường |
| Systemd unit | `/etc/systemd/system/tool-vision.service` | installer | Có từ template | lưu manifest |
| Moonraker updater block | `[update_manager tool-vision]` trực tiếp trong `moonraker.conf` | người dùng | Có | backup cùng config |
| Allowed services | `~/printer_data/moonraker.asvc` | Moonraker + installer | Không nên dựng thủ công | backup trước sửa |
| Installer backups | `~/printer_data/config_backups/tool-vision/` | installer | Không | giữ đến restore drill |

`~` là home của user chạy Klipper, không được hard-code `voron` trong logic.
Hai file JSON mặc định nằm ở root `config/` trong v3.2.1 và cũ hơn, rồi nằm
trong `Tool-Vision/` ở v3.2.2/RC1. Installer RC2 backup rồi copy các default còn
thiếu vào `Printer-Setup/`; đường dẫn được người dùng khai báo tường minh không
bị copy. File legacy luôn được giữ để include thủ công cũ tiếp tục hoạt động cho
đến khi người dùng đổi cấu hình và tự dọn sau khi xác minh.

## Schema hiện tại

### Learned state schema 2

Top-level:

```text
schema_version
tool_vision_version
reference_tool
updated
stations.camera?  -> position XYZ, safe_z, frame width/height
stations.switch?  -> position XYZ, safe_z, trigger_z
vision.profile?   -> detector profile schema 1
vision.transform? -> transform schema 2 (`v3.3.0-rc1`)
```

`StateStore` kiểm tra top-level, station position và số hữu hạn. Profile và
transform được host service kiểm tra sâu khi configure. Top-level schema không
tương thích bị bỏ qua trong RAM và ghi vào `last_error`; nested transform cũ bị
từ chối ở preflight XY. Chưa có migration/quarantine tự động (R-009).

Transform schema 2 bổ sung leave-one-out RMS, pixel noise, gain mm/pixel và
estimated/max uncertainty. Không thể suy ra các evidence này từ transform
schema 1 đã lưu, nên không có migration số học an toàn. Khi nâng từ `v3.2.2`,
phải backup `tool_vision_state.json`, cập nhật code/service đồng bộ rồi chạy lại
`TV_SETUP_CAMERA`. Klippy từ chối schema cũ trước khi heat/toolchange trong một
calibration XY; file backup gốc không bị tự động sửa. Station switch và kết quả
Z không cần dạy lại chỉ vì thay transform camera.

### Result schema 1

Top-level:

```text
schema_version
tool_vision_version
measured
mode
temperature
reference_tool
offsets
note
```

Mỗi tool có offset `x/y/z` theo mode và có thể có raw center/trigger, confidence
hoặc stability. File hiện chỉ giữ run thành công mới nhất; `TV_REPORT` chỉ dùng
result trong session Klipper hiện tại.

## Invariant dữ liệu

- Config người dùng và state/result phải nằm ngoài Git checkout.
- Không sửa state/result bằng tay khi Klipper đang chạy.
- JSON chỉ được thay bằng atomic write; migration tương lai phải backup trước.
- Không coi `tool_vision_version` cũ là lỗi nếu schema còn tương thích; nó ghi
  version tạo file gần nhất.
- Không dùng result nếu reference tool, camera/switch station hoặc hardware
  fingerprint không khớp run đang xét.
- Result là phép đo, không phải bằng chứng offset đã được áp.
- Support bundle phải redaction camera URL/credential và nội dung config nhạy
  cảm.

## Thiết kế lưu trữ mục tiêu (Planned)

R-009/R-015 cần chuyển từ “latest only” sang:

```text
printer_data/config/Printer-Setup/
  tool_vision.cfg
  tool_vision_state.json
  tool-vision-history/
    YYYY/MM/<run-id>.json
  tool-vision-quarantine/
    <timestamp>-invalid-state.json
```

Backup installer không nằm trong cây này; nó tiếp tục ở
`printer_data/config_backups/tool-vision/`. History/quarantine vẫn là thiết kế
đề xuất, chưa phải behavior runtime RC2.

Mỗi run record nên có:

- UUID/run ID, start/end/duration và phase cuối;
- ToolVision/Klipper/Moonraker/toolchanger revision;
- camera descriptor không có credential, frame resolution và profile/transform
  fingerprint;
- mode, requested/actual temperature, tool order;
- raw sample summary, rejected samples, uncertainty/repeatability indicators;
- primary error, cleanup errors, original/final tool và heater cleanup status;
- measured offsets và `applied: false` mặc định.

Đây là thiết kế đề xuất, chưa phải schema runtime. Phải có ADR, retention và
migration test trước khi triển khai.

## Retention đề xuất

- Giữ tối thiểu 10 local snapshots state/config gần nhất.
- Giữ mọi snapshot trước upgrade/schema/setup lại cho đến khi restore drill của
  release mới pass.
- Giữ release evidence và semantic release tags lâu dài trên remote; backup mã
  đang làm việc nằm trong thư mục local bị Git ignore.
- Log xoay vòng theo dung lượng/thời gian; giữ log liên quan incident cùng
  incident report.
- Có ít nhất một bản backup ngoài SBC/máy in cho config/state quan trọng.

Chi tiết thao tác nằm ở [`BACKUP_RESTORE.md`](BACKUP_RESTORE.md).
