# Quy ước viết code và chú thích

Tài liệu này là hợp đồng kỹ thuật cho code mới và code được sửa. Nó ưu tiên khả
năng kiểm chứng, an toàn máy và tương thích hơn việc đồng nhất style bằng một
lần refactor lớn. `AGENTS.md` ở root bắt buộc agent đọc tài liệu này trước khi
thay đổi code.

## Nguyên tắc chung

- Một thay đổi behavior phải đi cùng test chứng minh behavior trước/sau.
- Một hàm chỉ nên có một trách nhiệm có thể đặt tên rõ. Tách parsing, validation,
  I/O, quyết định và side effect khi việc tách giúp test failure path độc lập.
- Dùng tên chứa đơn vị hoặc hệ tọa độ khi có thể: `timeout_s`, `radius_mm`,
  `center_px`, `raw_trigger_z`. Không để đơn vị chỉ tồn tại trong trí nhớ người
  viết.
- Không dùng magic number cho motion, nhiệt, detector hoặc tolerance. Đặt tên
  constant, ghi nguồn/ý nghĩa và thêm test biên.
- Dữ liệu đi qua process/API/file phải có validation tại biên: kiểu, trường bắt
  buộc, finite number, range, kích thước và schema version.
- Ưu tiên code đơn giản, deterministic và replay được. Không tối ưu sớm code
  ảnh hoặc motion nếu chưa có profile/bằng chứng.
- Không refactor style trên diện rộng trong commit sửa safety. Nếu cần, tách
  commit/PR để diff behavior còn review được.

## Tương thích Python

Minimum Python chính thức chưa được chốt; xem WS0 và
[`COMPATIBILITY.md`](COMPATIBILITY.md). Cho đến khi matrix được phê duyệt:

- không tự động đổi toàn bộ code sang cú pháp/stdlib chỉ có ở Python mới;
- giữ syntax chạy được trên runtime Klipper mục tiêu và Python 3.11 đã quan sát;
- xem `%` formatting hoặc cấu trúc cũ trong Klippy là quyết định tương thích có
  thể có chủ ý, không phải lỗi cần autofix ngay;
- dependency hoặc syntax nâng minimum Python phải có test matrix, changelog và
  migration/release note;
- 4 spaces, UTF-8, newline cuối file; import chuẩn → third-party → nội bộ;
- tránh mutable default arguments và trạng thái module ẩn khó reset trong test.

Type hint được khuyến khích ở host code nếu không làm tăng minimum Python hoặc
phá Klipper loader. Tên và validation runtime vẫn là contract; type hint không
thay thế validation dữ liệu từ HTTP/config/JSON.

## Ranh giới module

### `klippy/extras/`

- Không import OpenCV/NumPy và không xử lý frame trong Klipper.
- Không chặn reactor bằng network, sleep hoặc công việc CPU dài. I/O liên
  process mới phải có deadline và kiến trúc async/job được review.
- Mọi motion phải đi qua guard homing/state/limit và xác định rõ raw position so
  với gcode position.
- Helper safety nên trả dữ liệu có nghĩa hoặc raise domain error; không trả
  sentinel mơ hồ như `None` nếu `None` có thể bị hiểu là success.
- Lệnh G-code phải có help rõ, validate tham số trước side effect và báo lỗi có
  hành động khắc phục.

### `server/`

- Camera/detector/transform mutation phải được serialize; request đọc không
  được thấy state nửa cập nhật.
- HTTP/camera I/O phải có connect/read deadline, giới hạn byte/pixel/frame và
  đóng resource ở mọi đường thoát.
- API lỗi dự kiến trả JSON ổn định với mã/chuỗi lỗi hữu ích; log server giữ
  detail chẩn đoán nhưng không lộ credential.
- Thuật toán ảnh phải test bằng corpus/replay. Synthetic image chỉ là test bổ
  sung, không đủ chứng minh phần cứng thật.

### Installer và shell

- Shell script dùng `set -euo pipefail`, quote biến đường dẫn và dùng `--` trước
  path khi command hỗ trợ.
- Preflight toàn bộ điều kiện có thể biết trước khi bắt đầu write.
- Không `rm -rf` target suy ra từ biến chưa validate; không ghi đè backup.
- File người dùng phải được copy/backup trước mutation. Fresh install, upgrade,
  interrupted install và uninstall là các behavior riêng cần test.
- Systemd, Moonraker include, service name và path phải là một contract thống
  nhất giữa installer, uninstaller, README và test.

## Error handling và cleanup

- Raise exception theo domain (`CameraError`, `DetectionError`,
  `ToolVisionError`, ...) với context đủ để operator xử lý.
- Không dùng `except Exception: pass`. Broad catch chỉ được dùng tại boundary
  cleanup/top-level đã xác định; phải lưu/log lỗi và không biến failure thành
  success.
- Khi primary operation và cleanup cùng fail, giữ cả hai. Primary error giải
  thích vì sao task fail; cleanup error cho biết máy có thể còn ở trạng thái
  không an toàn.
- `finally` dùng cho resource/heater do task sở hữu, nhưng phải kiểm tra state
  trước motion recovery. MCU shutdown không được giả định là còn điều khiển được.
- Retry phải hữu hạn, có backoff/deadline phù hợp và chỉ retry operation an toàn
  khi lặp. Không retry motion/probe mù quáng.
- Không ghi state/result hoàn chỉnh nếu calibration chưa qua tất cả gate.

## Số học và hệ tọa độ

- Kiểm tra `NaN`/`inf`, rank, condition, residual, range và số sample trước khi
  dùng kết quả numerical.
- Đặt tên rõ `raw`, `gcode`, `pixel`, `machine`, `reference`; không trộn các hệ
  trong cùng tuple không được mô tả.
- Mọi thay đổi dấu XY/Z cần test độc lập với cả giá trị âm và dương, cập nhật
  `ARCHITECTURE.md` và ADR.
- Round chỉ để hiển thị hoặc ở boundary đã định nghĩa. Giữ raw precision cho
  transform, aggregation và result evidence.
- Threshold mới phải trỏ tới upstream revision hoặc artifact đo; ghi rõ unit,
  sample population và điều kiện thoát khỏi experimental.

## State, config và version

- Config người dùng chỉ chứa thông tin phần cứng không thể tự khám phá cùng
  advanced override thực sự cần thiết. Không đưa giá trị có thể teach/derive về
  `.cfg` chỉ để implementation dễ hơn.
- JSON state/result có schema version. Thay schema phải có reader/migration cho
  dữ liệu cũ hoặc fail có hướng dẫn và backup/quarantine rõ.
- Ghi file theo kiểu atomic: write file tạm cùng filesystem, flush/close rồi
  replace. Không để JSON nửa file sau power loss.
- Không ghi secrets, camera credential hoặc IP riêng vào log/result/support
  bundle.
- Version hiện đang lặp ở nhiều module (R-016). Khi sửa release, dùng contract
  test để bảo đảm mọi nơi đồng nhất cho tới khi có single source of truth.

## Quy ước chú thích

Chú thích phải giải thích điều code không thể tự nói: **vì sao**, invariant,
nguy cơ vật lý, dấu/hệ tọa độ, nguồn quyết định hoặc lý do compatibility. Không
dịch lại từng dòng code sang tiếng Anh/Việt.

Chú thích tốt:

```python
# Axiscope-compatible sign: a higher raw trigger Z is a positive relative Z.
z_offset = trigger_z - reference_trigger_z

# Clear every target owned by this calibration even when a later probe fails.
# Motion recovery is separate because Klipper may already be in shutdown.
clear_owned_heaters()
```

Chú thích không có giá trị:

```python
# Subtract reference from trigger.
z_offset = trigger_z - reference_trigger_z

# Loop over tools.
for tool in tools:
    ...
```

Quy tắc cụ thể:

- Viết comment sát invariant/nhánh khó hiểu; không viết tiểu luận giữa hàm.
- Khi kế thừa nguồn, ghi project + pinned revision hoặc trỏ tới tài liệu đã ghi
  revision. Không copy code upstream khi chưa rõ license.
- Comment safety nêu điều kiện trước/sau và failure state, không chỉ “be safe”.
- Public API, state schema và command behavior dùng docstring ngắn mô tả
  contract. Internal helper rõ nghĩa không bắt buộc docstring hình thức.
- `TODO` phải có Risk ID hoặc issue và exit condition, ví dụ:

  ```python
  # TODO(R-001): move HTTP off the Klipper reactor.
  # Exit: delayed-host integration test proves bounded reactor latency.
  ```

- Không để comment chứa version cũ như sự thật hiện tại. Dùng “v3.2.1 and
  older” chỉ khi mô tả migration/lịch sử.
- Khi code đổi làm comment sai, sửa/xóa comment và regression test trong cùng
  commit.

## Logging và thông báo người dùng

- Message bắt đầu bằng operation/tool khi cần truy vết, dùng đơn vị và giá trị
  thực tế; không chỉ ghi “failed”.
- Tách trạng thái `Observed`, `Planned`, `Unsupported` và `Unknown`; không báo
  success trước health/version/readiness gate.
- Không log frame/URL đầy đủ mặc định. Artifact debug phải opt-in, có giới hạn,
  quyền truy cập và thời hạn lưu.
- Giữ message G-code ngắn, nhưng lỗi phải nói operator nên kiểm tra/chạy gì tiếp.

## Test và review

- Tên test mô tả behavior, không mô tả implementation.
- Mỗi bug cần regression test tại tầng thấp nhất tái hiện đúng lỗi; motion/heat
  vẫn cần integration/HIL theo gate.
- Test cả success, boundary và failure/cleanup. Với numerical code, test noise,
  outlier, degeneracy và non-finite input.
- Mock ở process/hardware boundary, không mock mất chính logic cần chứng minh.
- Không cập nhật snapshot/expected chỉ để test xanh nếu chưa giải thích behavior
  change.

Checklist đầy đủ nằm tại [`TESTING.md`](TESTING.md) và
[`DEVELOPMENT.md`](DEVELOPMENT.md).
