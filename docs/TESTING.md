# Chiến lược kiểm thử

## Baseline hiện tại

Baseline audit `v3.2.1` có 46 test pass. `v3.2.2` thêm contract test cho đường
dẫn dữ liệu và có 47 test pass. Nhánh `v3.3.0-rc1` có 70 test pass ngày
2026-08-22 sau khi thêm regression detector/transform/camera/concurrency/host
rehydration. Branch coverage của RC được đo cùng suite đó:

- toàn cây gồm test: 73% (baseline 69%);
- `klippy/extras/tool_vision.py`: 40% (baseline 32%);
- `klippy/extras/tool_vision_client.py`: 15%;
- host service modules thay đổi: camera 71%, detection 83%, transform 75%, app
  75%.

Coverage thấp ở hai module điều phối safety là rủi ro, không chỉ là chỉ số style.
Mục tiêu ngắn hạn là không giảm baseline; mục tiêu trước release stable là các
nhánh safety/recovery được test theo behavior, không chạy theo một con số tổng
đẹp nhưng bỏ sót failure path.

## Lệnh kiểm tra local

```bash
python -m unittest discover -s tests -v
python -m compileall -q klippy server tests
python -m coverage run --branch -m unittest discover -s tests
python -m coverage report -m
python -m ruff check klippy server tests
python -m pip_audit -r server/requirements.txt
bash -n install.sh
bash -n uninstall.sh
git diff --check
```

Ruff cần một cấu hình target Python được chốt trong WS0. Trước đó không tự động
áp hàng loạt gợi ý hiện đại hóa vì Klippy có thể cần tương thích Python cũ hơn
máy phát triển.

## Kim tự tháp test

### L0 — Static/contract

- Python compile; Bash syntax; config parser.
- Không có lệnh tự ghi production offset.
- Version/API/schema/path/service names đồng nhất.
- Moonraker updater và systemd template parse được.
- Dependency audit và license inventory.

### L1 — Unit

- Dấu XY/Z, axis limits, safe Z và station envelope.
- Transform rank/condition/residual/sensitivity/outlier/holdout.
- Detector learning, ambiguity, blur, distractor, frozen frame và resolution.
- State validation, migration, quarantine, atomic/backup behavior.
- Toolchanger adapter cho từng contract được hỗ trợ.
- Recovery state machine với exception ở mọi bước.

### L2 — Component/API

- Flask API với camera fake có barrier để kiểm tra concurrency.
- Camera HTTP chậm, response quá lớn, malformed MJPEG, reconnect và timeout.
- VisionClient với delayed/hung/malformed server mà không khóa reactor giả lập.
- Job start/poll/timeout/cancel/service restart.

### L3 — Klipper integration/simulator

- Load extension qua config thật, không bypass `__init__`.
- Toolchange transform thực, `get_position` raw/gcode và offset dấu ±.
- Printer states: unhomed, printing, paused, shutdown, toolchanger chưa init.
- Probe: open, stuck-triggered, no-trigger, tolerance fail và MCU shutdown.
- Heater: missing extruder, timeout, toolchange fail và cleanup fail.

### L4 — Deployment integration

- Fresh install trong image Debian hỗ trợ.
- Upgrade N-1 → N qua Moonraker.
- Failure injection ở từng installer step và rollback.
- Uninstall + restore file/symlink/config cũ.
- ARM64 và ít nhất một platform phát triển khác trong compatibility matrix.

### L5 — HIL

- Máy idle, không có print; operator và emergency stop sẵn sàng.
- Backup config/state/result và ghi firmware/revision trước run.
- Chạy setup/calibrate lặp với các tool/hardware đã đăng ký.
- Kiểm tra vị trí, nhiệt, tool cuối, heater target, Klipper state và file result.
- Chỉ sau pass HIL mới canary release qua Moonraker.

## Image corpus

Corpus không được chỉ có hình tròn tổng hợp. Manifest tối thiểu cho mỗi frame:

- corpus version và checksum;
- camera model/backend/resolution/rotation/flip;
- nozzle class, trạng thái sạch/bẩn và approximate focus/light condition;
- nhãn center hoặc `no_nozzle`/`ambiguous`/`frozen`;
- quyền sử dụng ảnh và thông tin redaction;
- expected accept/reject, không ghi threshold thuật toán vào nhãn.

Nhóm bắt buộc:

- dark/light nozzle, backlight, glare, shadow;
- nhiều kích thước nozzle và camera angle;
- blur, noise, compression, exposure change;
- vật tròn gây nhiễu gần tâm;
- nozzle ngoài tâm nhưng trong 2 mm envelope;
- frame lặp/frozen và resolution đổi;
- ảnh quá lớn hoặc hỏng.

Dataset lớn lưu ngoài Git bằng kho artifact có version/checksum; Git chỉ giữ
manifest và script replay. Không commit URL camera có credential.

## Repeatability và accuracy

Không đặt một tolerance “chuẩn cho mọi máy” khi chưa có dữ liệu. Quy trình chốt
ngưỡng:

1. Ghi raw sample/result của nhiều vòng trên mỗi hardware class.
2. Tách repeatability (độ phân tán) khỏi accuracy so với chuẩn độc lập.
3. So sánh nóng/nóng cùng nhiệt; không trộn nguội/nóng.
4. Dùng fixture/reference measurement độc lập hoặc print validation được định
   nghĩa trước.
5. Đề xuất threshold từ percentile/confidence interval, review rồi ghi ADR.

Release evidence tối thiểu phải có số run, số tool, failure count, distribution
XY/Z và baseline comparison. Trước khi có threshold được phê duyệt, gate là
“không regression so với baseline đã lưu”, không phải một con số tự suy diễn.

## Failure injection bắt buộc cho safety change

| Điểm lỗi | Kết quả cần xác nhận |
|---|---|
| HTTP timeout/malformed JSON | Không block reactor; job kết thúc có lỗi rõ |
| Camera mất giữa move | Dừng correction, recovery và không lưu state mới |
| Toolchange fail | Không đi tới station; heater cleanup chạy |
| Probe no-trigger/tolerance | Retract nếu Klipper còn ready; không ghi result hoàn chỉnh |
| Original tool restore fail | Primary + cleanup error đều được giữ |
| Heater-off fail | Status báo unsafe cleanup, không báo success im lặng |
| Disk full/permission | File cũ còn nguyên; không có JSON nửa file |
| Service restart giữa job | Klipper nhận lỗi có giới hạn; có thể retry sau khi idle |
| Update bị ngắt | Runtime/config trở về phiên bản nhất quán |

## Release gate theo loại thay đổi

| Thay đổi | Gate tối thiểu |
|---|---|
| Docs only | links/config examples/diff check |
| Host pure logic | L0–L2 + corpus replay liên quan |
| Klipper orchestration | L0–L3 + fault injection |
| Motion/probe/heater | L0–L3 + HIL |
| Installer/schema/dependency | L0–L4 + restore drill |
| Detector/transform behavior | corpus replay + HIL repeatability |

Không dùng máy production làm nơi phát hiện test đầu tiên.

## Evidence `v3.3.0-rc1` hiện có

Unit/component suite đã tái hiện rồi khóa các behavior sau:

- hai vật khác vị trí cùng khớp detector phải fail;
- grayscale/profile threshold sai phải thành domain error;
- transform tiny-pixel, rank thấp, >25% outlier hoặc quá 64 sample phải fail;
- correction có uncertainty và schema contract phải khớp hai process;
- HTTP frame vượt pixel budget và RTSP open thiếu deadline contract;
- configure/start race có barrier, failed configure giữ runtime cũ;
- frozen observation sau commanded move, correction thiếu field và acceptance
  bỏ qua uncertainty phải fail;
- host rehydrate xảy ra trước heat/toolchange; transform schema cũ fail sớm.

70 test này không thay thế corpus/HIL. R-005/R-006/R-010/R-017 chưa được đóng
chỉ bằng ảnh tròn tổng hợp và fake camera.
