# ToolVision 3

ToolVision tự động đo **X/Y/Z offset tương đối** giữa các đầu in trên máy
Klipper nhiều tool. Bản 3 được viết lại theo workflow của
[kTAMV](https://github.com/TypQxQ/kTAMV) cho camera XY và
[Axiscope](https://github.com/nic335/Axiscope) cho công tắc Z, nhưng không yêu
cầu người dùng khai báo trước vị trí fixture hoặc hàng loạt tham số OpenCV.

Workflow bình thường chỉ còn bốn nút/lệnh:

1. đưa T0 đến gần tâm camera → `TV_SETUP_CAMERA`;
2. đưa T0 lên trên switch → `TV_SETUP_SWITCH`;
3. chạy `TV_CALIBRATE MODE=XYZ`;
4. xem lại bằng `TV_REPORT`.

Kết quả mặc định là **report-only**. ToolVision không âm thầm sửa offset đang
dùng, không gọi `SET_TOOL_PARAMETER`, `SAVE_TOOL_PARAMETER` hoặc `SAVE_CONFIG`.

## Điều gì được tự động hóa?

- Vị trí camera và switch được học từ vị trí hiện tại của T0 rồi lưu nguyên tử.
- Camera được tự dò từ [Moonraker webcam API](https://moonraker.readthedocs.io/en/latest/external_api/webcams/).
- Flip/rotation của camera do Moonraker quản lý được áp dụng tự động.
- Tool được đọc động từ toolchanger; không cần danh sách `tool_numbers`.
- Detector thử nhiều chiến lược dark/light, adaptive/Otsu/edge, chọn kết quả ổn
  định gần tâm và học hình học vòi in từ ảnh thật.
- Ảnh giữ nguyên độ phân giải; không resize cố định 640×480.
- Pixel/mm được fit tự động từ đúng chu trình mười điểm bán kính 0,5 mm của
  kTAMV, có loại điểm ngoại lai và kiểm tra ma trận.
- Z dùng năm mẫu, median, tolerance 0,05 mm và hai lần retry theo khuyến nghị
  hiện tại của [klipper-toolchanger tools_calibrate](https://github.com/viesturz/klipper-toolchanger/blob/main/tools_calibrate.md).
- ToolVision nâng Z trước khi đi XY, kiểm tra homed/printing/giới hạn động học và
  kiểm tra switch đang mở trước khi probe.

Độ nét được báo dưới dạng chỉ số tương đối, không còn ngưỡng tuyệt đối kiểu
`focus > 0.006`. Nghiên cứu về focus operators cho thấy kết quả phụ thuộc noise,
contrast, saturation và kích thước cửa sổ
([Pertuz, Puig & Garcia, 2013](https://doi.org/10.1016/j.patcog.2012.11.011)).
Vì vậy tiêu chí “ảnh dùng được” của ToolVision là: vòi được nhận diện ổn định
qua nhiều frame **và** phép biến đổi chuyển động vượt kiểm tra sai số.

## Phạm vi an toàn

ToolVision không thể suy ra mọi kẹp, giá đỡ hay vật cản chỉ từ một camera hướng
lên. Người vận hành vẫn phải bảo đảm đường nâng Z thẳng đứng an toàn. Nếu fixture
cần khoảng hở lớn hơn mặc định 5 mm, truyền một lần khi setup:

```gcode
TV_SETUP_CAMERA SAFE_Z=25
TV_SETUP_SWITCH SAFE_Z=25
```

Nozzle phải sạch. Offset cơ khí đo trên switch có thể khác offset in tối ưu do
lực switch, nhựa bám, nhiệt độ nozzle/bed và giãn nở khung. Đặc biệt, không so
sánh một kết quả đo nguội với một kết quả đo nóng. Luôn đo lặp lại ở cùng nhiệt
độ và xác nhận bằng bản in alignment/first-layer trước khi áp dụng.

Không bật đồng thời các section sau vì chúng cùng có thể cấp phát
`probe_multi_axis`:

```ini
[tool_vision]
[axiscope]
[tools_calibrate]
```

ToolVision cần file Python `tools_calibrate.py` từ klipper-toolchanger, nhưng
section `[tools_calibrate]` phải để tắt.

## Cấu hình tối thiểu

File [`tool_vision.cfg`](tool_vision.cfg) mặc định không cần giá trị camera:

```ini
[tool_vision]
# pin: ^PF2   # chỉ mở khi cần đo Z, thay bằng pin thật
```

Nếu Moonraker chỉ có một webcam enabled, ToolVision dùng webcam đó. Nếu có nhiều
camera, nó chỉ tự chọn khi đúng một camera có tên/vị trí chứa từ khóa nozzle,
tool, align, kTAMV hoặc ToolVision. Trường hợp còn mơ hồ sẽ dừng và liệt kê tên,
không chọn đại theo thứ tự. Khi đó chỉ cần thêm:

```ini
camera_name: nozzle
```

Camera chưa đăng ký với Moonraker mới cần nguồn trực tiếp:

```ini
camera_source: http://127.0.0.1:8080/?action=snapshot
# Hoặc MJPEG/RTSP, /dev/video0, hay OpenCV index 0
```

`pin` là thông tin phần mềm không thể tự đoán. Dùng cú pháp invert/pull-up chuẩn
của Klipper và kiểm tra điện bằng lệnh chính thức `QUERY_ENDSTOPS` trước lần
probe đầu tiên.

## Cài đặt

Yêu cầu:

- Klipper + Moonraker;
- [klipper-toolchanger](https://github.com/viesturz/klipper-toolchanger) bản có
  `tools_calibrate.py`;
- camera hướng lên cho XY; switch tiếp xúc cho Z là tùy chọn.

Trên máy Klipper:

```bash
git clone --recurse-submodules https://github.com/IDcrazy123/Tool-Vision.git
cd Tool-Vision
./install.sh
```

Installer dùng chính Git checkout `~/Tool-Vision` làm runtime, tạo venv riêng,
service `tool-vision.service`, bốn symlink extension và file cấu hình có thể sửa
trong `~/printer_data/config/Tool-Vision/`. Nó không sửa `printer.cfg`.

Installer đồng thời tạo:

```text
~/printer_data/config/Tool-Vision/moonraker_update_manager.conf
```

và thêm một include vào `moonraker.conf` sau khi đã sao lưu file đó. Installer
cũng sao lưu rồi thêm đúng dịch vụ `tool-vision` vào
`~/printer_data/moonraker.asvc`, theo cơ chế dịch vụ được phép của Moonraker.
Checkout Git và cấu hình người dùng được tách riêng, nên Moonraker vẫn yêu cầu
repository sạch nhưng người dùng có thể sửa `tool_vision.cfg` bình thường.

Thêm include rồi restart:

```ini
[include Tool-Vision/tool_vision.cfg]
```

```gcode
FIRMWARE_RESTART
TV_STATUS
```

### Cập nhật trong Mainsail/Fluidd

Sau lần chạy installer đầu tiên, trang **Machine → Update Manager** có mục
`tool-vision` giống Klipper. Nhấn refresh rồi update tại đó; Moonraker sẽ:

1. fetch/pull đúng Git branch đã được installer ghi nhận;
2. cập nhật dependency trong `~/tool-vision-env` nếu requirements thay đổi;
3. restart `tool-vision` và `klipper` sau khi cập nhật.

Moonraker tự kiểm tra phiên bản mới và Mainsail hiển thị nút cập nhật; thao tác
cập nhật vẫn do người dùng bấm để không làm gián đoạn một máy đang hoạt động.
Không cần SSH hay chạy lại `install.sh` cho các lần cập nhật thông thường.

Moonraker không cho update trong lúc đang in và chỉ quản lý repository sạch.
Không sửa file bên trong `~/Tool-Vision`; mọi cấu hình cần chỉnh nằm ở
`~/printer_data/config/Tool-Vision/tool_vision.cfg`.

Máy đã cài bản ToolVision dùng runtime copy cũ chỉ cần cập nhật Git thủ công và
chạy `./install.sh` **một lần** để chuyển service/symlink sang checkout Git và
đăng ký Update Manager. Những lần sau có thể cập nhật trên giao diện.

Khi nâng từ ToolVision 2, installer sao lưu cấu hình mẫu cũ với hậu tố
`.pre-v3-<timestamp>` trước khi đặt file tối giản mới. State schema 1 không được
đọc như schema 2; hãy setup lại hai station để tránh dùng nhầm dữ liệu cũ.

## Setup một lần

### 1. Camera XY

1. Home XYZ, gắn T0, xác nhận offset cấu hình của T0 đang là XYZ zero và làm
   sạch nozzle. Bản 3.2.1 chưa hỗ trợ an toàn reference tool có offset non-zero;
   giới hạn này được theo dõi tại `R-002` trong risk register.
2. Jog T0 đến gần tâm ảnh camera; chỉnh Z/focus vật lý để vòi tương đối rõ.
3. Bảo đảm có khoảng trống cho chuyển động 0,5 mm quanh điểm hiện tại.
4. Chạy:

```gcode
TV_SETUP_CAMERA
```

Một lệnh này sẽ:

- tìm hoặc mở camera;
- học detector ở độ phân giải thật;
- yêu cầu ba detection liên tiếp ổn định;
- chạy mười vị trí calibration kTAMV;
- yêu cầu tối thiểu 8/10 điểm hợp lệ;
- fit ma trận 2D, loại điểm sai vượt 20%, kiểm tra rank/condition/residual;
- tự center T0 rồi lưu XYZ camera, safe Z, detector và transform.

### 2. Switch Z

1. Khai báo `pin`, restart và kiểm tra trạng thái bằng `QUERY_ENDSTOPS`.
2. Với T0 đang gắn, jog nozzle thẳng trên switch, cách điểm trigger dưới 10 mm.
3. Chạy:

```gcode
TV_SETUP_SWITCH
```

ToolVision xác nhận switch chưa trigger, probe nhiều mẫu, quay lại approach Z và
lưu vị trí/trigger chuẩn của T0. Không cần nhập X/Y/Z switch trong `.cfg`.

## Đo tất cả tool

```gcode
TV_CALIBRATE MODE=XYZ
```

Hoặc chỉ đo một hệ:

```gcode
TV_CALIBRATE MODE=XY
TV_CALIBRATE MODE=Z
```

### Nhiệt độ khi đo

Lõi Axiscope không ép nhiệt độ, nhưng cấu hình mẫu chính thức của Axiscope dùng
`M104 T... S150` để làm nóng mọi tool trước chu trình và trả chúng về `S0` khi
xong. Macro `CALIBRATE_ALL_OFFSETS` cũ của klipper-toolchanger trên máy đối
chiếu cũng chờ nozzle đạt 150 °C trước khi chạm switch. ToolVision hỗ trợ cùng
workflow mà không thêm giá trị bắt buộc vào `.cfg`:

```gcode
TV_CALIBRATE MODE=Z
```

ToolVision tự dùng 150 °C, đặt target cho tất cả tool trước để chúng nóng song
song, chờ lại từng tool sau khi pickup bằng `M109`, rồi mới đo. Mọi heater được
trả về 0 khi kết thúc **hoặc khi calibration phát sinh lỗi**. Người dùng bình
thường không cần can thiệp vào nhiệt độ.

Khuyến nghị thực tế:

- 150 °C là mốc tương thích với Axiscope mẫu và macro cũ của máy này;
- nozzle cần sạch trước khi bắt đầu; với `MODE=XY/XYZ`, kiểm tra nhựa rỉ không
  che hình camera;
- trường hợp phần cứng/vật liệu đặc biệt mới cần override `TEMP=...`; `TEMP=0`
  là chế độ đo nguội chủ động.

Máy có brush có thể cấu hình hook chạy đúng sau pickup và sau khi đạt nhiệt:

```ini
[tool_vision]
after_select_gcode:
  CLEAN_NOZZLE TEMP=150
```

Hook là tùy chọn vì ToolVision không thể tự suy ra vị trí/hành trình brush an
toàn trên phần cứng bất kỳ.

ToolVision tự chọn các tool đã đăng ký. Với mỗi tool, camera closed-loop đưa
nozzle về cùng tâm ảnh; switch đo trigger Z tại cùng fixture. Nếu XY vừa được đo,
kết quả đó cũng được dùng để đưa nozzle chính xác hơn lên switch.

Quy ước dấu được cố định và có test regression:

```text
XY[n] = raw_center_position[n] - raw_center_position[T0]
 Z[n] = raw_trigger_z[n]       - raw_trigger_z[T0]
```

Đây là hướng dấu của kTAMV/current toolchanger camera-align cho XY và Axiscope
cho Z. Xem đặc tả kỹ thuật tại [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

Kết quả được lưu ở:

```text
~/printer_data/config/Tool-Vision/tool_vision_results.json
```

State học một lần được lưu riêng ở:

```text
~/printer_data/config/Tool-Vision/tool_vision_state.json
```

Hãy chạy ít nhất ba lần, so sánh độ lặp và backup offset hiện tại trước khi áp
dụng thủ công. Kết quả là **tương đối với reference**, không phải giá trị tuyệt
đối để chép mù quáng. Với v3.2.1, reference tool phải có configured XYZ offset
zero trong lúc setup/calibrate; preflight tự động cho điều kiện này nằm trong
[lộ trình R-002](docs/RISK_REGISTER.md#r-002--reference-offset-và-station-envelope).

Từ v3.2.2, state/result mặc định nằm cùng thư mục `Tool-Vision/` thay vì làm
rối root `config`. Installer tự di chuyển hai file mặc định của v3.2.1 trở về
đúng chỗ và lưu bản sao trong `~/printer_data/config_backups/tool-vision/`.
Các đường dẫn `state_file`/`result_file` đã đặt tường minh luôn được giữ nguyên.

## Lệnh và giao diện

| Nút/lệnh ngắn | Lệnh lõi | Công dụng |
|---|---|---|
| `TV_STATUS` | `TOOL_VISION_STATUS` | trạng thái setup/service/lỗi cuối |
| `TV_SETUP_CAMERA` | `TOOL_VISION_SETUP_CAMERA` | học camera tại T0 hiện tại |
| `TV_SETUP_SWITCH` | `TOOL_VISION_SETUP_SWITCH` | học switch tại T0 hiện tại |
| `TV_CALIBRATE` | `TOOL_VISION_CALIBRATE` | tự gia nhiệt 150 °C, đo rồi tắt heater |
| `TV_REPORT` | `TOOL_VISION_REPORT` | in lại kết quả của session |

Các macro này hiện thành nút trong Mainsail/Fluidd. Người dùng bình thường không
cần gọi API hay chỉnh tham số detector.

Ảnh chẩn đoán mới nhất:

```text
http://127.0.0.1:8085/api/v2/frame
```

## Chẩn đoán

```bash
systemctl status tool-vision.service
journalctl -u tool-vision.service -n 100 --no-pager
curl http://127.0.0.1:8085/api/v2/health
```

Các lỗi có chủ đích:

- `camera discovery is ambiguous`: đặt `camera_name` hoặc `camera_source`;
- `resolution changed`: camera đổi độ phân giải, chạy lại setup camera;
- `switch is already triggered`: nâng nozzle, kiểm tra dây/polarity;
- `< 8/10 points`: làm sạch nozzle, chỉnh focus/ánh sáng rồi setup lại;
- `correction exceeded 2 mm`: đưa nozzle gần tâm hơn trước setup/đo;
- `probe_multi_axis conflict`: tắt `[axiscope]` và `[tools_calibrate]`.
- heater vẫn chạy sau khi dừng bằng emergency stop/shutdown: dùng
  `TURN_OFF_HEATERS`; cleanup G-code không thể chạy sau khi Klipper đã shutdown.

## Kiến trúc và kiểm thử

```text
Klipper                              Host service
klippy/extras/tool_vision.py         server/app.py
  motion + probe + orchestration       API + one-job queue
tool_vision_toolchanger.py           server/camera.py
  API compatibility                    Moonraker discovery/capture
tool_vision_state.py                 server/detection.py
  schema + atomic JSON                 learned native detector
tool_vision_client.py                server/transform.py
  short request + reactor polling      robust pixel→machine fit
```

OpenCV/NumPy không chạy trong process Klipper. Host chỉ trả quan sát; nó không
được quyền ra lệnh chuyển động. Chạy test trên máy phát triển:

```bash
python -m unittest discover -s tests -v
```

Các test bao phủ camera discovery mơ hồ, URL Moonraker port 80, MJPEG/native
frame, profile detection, focus tương đối, thay đổi resolution, 10-point fit và
outlier, dấu XYZ, motion lift-first, adapter toolchanger cũ/mới, state atomic,
API v2 và contract installer/config.

## Nguồn logic và điểm cải thiện

- [kTAMV](https://github.com/TypQxQ/kTAMV): nhiều kiểu preprocessing, detection
  ổn định, pattern mười điểm 0,5 mm, yêu cầu ít nhất 75% điểm và centering. Bản
  mới bỏ giả định resize 640×480, lưu profile/transform sau restart và thêm kiểm
  tra ambiguity/rank/condition/residual.
- [Axiscope](https://github.com/nic335/Axiscope): dùng
  `PrinterProbeMultiAxis`, trigger delta theo T0 và ý tưởng lấy vị trí switch hiện
  tại. Ví dụ chính thức preheat mọi tool ở 150 °C và cung cấp hook sau pickup;
  ToolVision kế thừa hai điểm này nhưng bổ sung chờ nhiệt từng tool và cleanup
  heater cả khi phép đo lỗi. Bản mới cũng lưu vị trí nguyên tử, kiểm tra switch
  mở và hỗ trợ API toolchanger hiện tại.
- [klipper-toolchanger tools_calibrate](https://github.com/viesturz/klipper-toolchanger/blob/main/tools_calibrate.md):
  nguồn probe primitive, sampling và clean-nozzle guidance.
- [klipper-toolchanger camera-align example](https://github.com/viesturz/klipper-toolchanger/blob/main/examples/camera-tool-align.cfg):
  đối chiếu hướng dấu XY với API transform mới.
- [Moonraker Webcam Management](https://moonraker.readthedocs.io/en/latest/external_api/webcams/):
  nguồn chính thức cho auto-discovery, URL, flip và rotation metadata.
- [Klipper G-Codes](https://www.klipper3d.org/G-Codes.html): nguồn chính thức cho
  `QUERY_ENDSTOPS`, lưu/phục hồi trạng thái G-code và hành vi console.

Hai submodule Axiscope/kTAMV chỉ là nguồn tham chiếu phát triển, không được copy
vào runtime printer.

## Quản trị dự án và lộ trình

Bộ tài liệu bảo trì dài hạn nằm tại [`docs/README.md`](docs/README.md), gồm:

- [audit mã nguồn 2026-08-22](docs/AUDIT_2026-08-22.md) và
  [risk register](docs/RISK_REGISTER.md);
- [lộ trình theo safety gate](docs/PROJECT_PLAN.md),
  [quy trình phát triển](docs/DEVELOPMENT.md) và
  [chiến lược test/HIL](docs/TESTING.md);
- [runbook vận hành](docs/OPERATIONS.md),
  [dữ liệu/lưu trữ](docs/DATA_AND_STORAGE.md) và
  [backup/restore](docs/BACKUP_RESTORE.md);
- [ma trận tương thích](docs/COMPATIBILITY.md) và
  [checklist phát hành](docs/RELEASE.md).

Baseline 3.2.1 được đánh giá là pilot có giám sát, report-only. Các rủi ro P0/P1
trong register phải được xử lý và có bằng chứng trước khi tuyên bố hỗ trợ ổn định
đa phần cứng hoặc thêm chức năng tự áp offset.

## English quick start

ToolVision 3 measures relative XYZ offsets on multi-tool Klipper printers. The
normal configuration is empty for camera-only XY and needs only `pin` for Z.
Home XYZ, mount T0, jog it near the upward camera center and run
`TV_SETUP_CAMERA`; jog T0 above the contact switch and run `TV_SETUP_SWITCH`;
then run `TV_CALIBRATE MODE=XYZ`. Camera metadata is discovered from Moonraker.
Calibration automatically heats all tools to 150 C, waits after each pickup,
and turns every tool heater off on success or failure. If several webcams are
ambiguous, set `camera_name`. Results are report-only and must be repeat-tested
before manual application.

## Gỡ cài đặt

```bash
./uninstall.sh
```

Service, bốn symlink và mục Moonraker Update Manager được gỡ. Git checkout,
state, result, cấu hình và backup được giữ lại. Thêm `--purge-venv` chỉ khi muốn
xóa cả môi trường Python riêng.
