# Risk register

Baseline khởi tạo: ToolVision `v3.2.1`, 2026-08-22. Đây là tài liệu sống; mỗi
rủi ro mới cần một ID ổn định và không được xóa sau khi đóng.

## Quy ước

| Mức | Ý nghĩa |
|---|---|
| P0 — Critical | Có thể làm gián đoạn realtime/safety; chặn release stable |
| P1 — High | Có thể gây chuyển động sai, kết quả sai, mất khả năng rollback hoặc hỏng workflow chính |
| P2 — Medium | Giảm độ tin cậy, bảo mật cục bộ, khả năng chẩn đoán hoặc bảo trì |
| P3 — Low | Nợ kỹ thuật có phạm vi nhỏ, chưa ảnh hưởng trực tiếp đến phép đo |

Trạng thái: `Open`, `Mitigating`, `Accepted`, `Closed`. Chỉ dùng `Closed` khi có
commit, test và bằng chứng nghiệm thu. “Chưa gặp trên máy pilot” không phải bằng
chứng đóng.

## Danh sách tóm tắt

| ID | Mức | Rủi ro | Trạng thái | Workstream |
|---|---|---|---|---|
| R-001 | P0 | HTTP đồng bộ có thể chặn reactor Klipper | Open | WS1 |
| R-002 | P1 | Reference offset/station envelope chưa được preflight | Open | WS1 |
| R-003 | P1 | Khôi phục tool, G-code state và retract khi lỗi chưa chắc chắn | Open | WS1 |
| R-004 | P1 | Heater cleanup/capability khác nhau giữa phần cứng | Open | WS1 |
| R-005 | P1 | Transform và detector thiếu gate vật lý/frozen-frame | Mitigating | WS2 |
| R-006 | P1 | Không có corpus ảnh thật, HIL matrix và chuẩn độ lặp | Open | WS2 |
| R-007 | P1 | Install/upgrade/uninstall chưa transactional | Open | WS3 |
| R-008 | P1 | Dependency chưa khóa, không có CI/Python matrix | Open | WS3 |
| R-009 | P1 | State migration, backup và lịch sử kết quả chưa đầy đủ | Open | WS3 |
| R-010 | P1 | OpenCV capture có thể treo; ảnh giải nén chưa giới hạn pixel | Mitigating | WS2 |
| R-011 | P1 | Tương thích toolchanger mới/cũ chưa có contract integration | Open | WS1 |
| R-012 | P1 | Repository chưa có LICENSE/chính sách quyền sử dụng rõ ràng | Open | WS0 |
| R-013 | P2 | Race giữa configure và start_job trong host service | Mitigating | WS2 |
| R-014 | P2 | API không auth nếu bind ra ngoài loopback | Open | WS3 |
| R-015 | P2 | Quan sát lỗi, run ID và audit trail còn yếu | Open | WS4 |
| R-016 | P3 | Version khai báo ở nhiều file có thể lệch | Mitigating | WS0 |
| R-017 | P1 | Host restart làm mất camera runtime trước XY calibration | Mitigating | WS2 |

## Phân tích và điều kiện đóng

### R-001 — HTTP đồng bộ trong Klipper reactor

- Bằng chứng: `VisionClient.request()` dùng `urllib.request.urlopen()` trực tiếp;
  `_configure_server()`, `_detect()`, fit và correction đều gọi từ command
  handler của Klipper. Timeout mỗi request có thể tới 5–8 giây.
- Tác động: camera/Moonraker/service chậm có thể giữ event loop Klipper, gây
  latency lớn hoặc MCU communication timeout.
- Giảm thiểu hiện tại: service mặc định ở localhost, job camera chạy ở host
  worker và Klipper chỉ poll. Điều này giảm thời gian xử lý dài nhưng không làm
  từng HTTP request thành non-blocking.
- Giải pháp: thiết kế transport không chặn được tích hợp với reactor hoặc một
  worker boundary đã được Klipper upstream chấp nhận; thêm deadline tổng và
  cancel job. Không đưa thread/socket tự phát vào Klippy trước khi có design
  review.
- Đóng khi: fault-injection làm endpoint treo/chậm mà reactor latency vẫn trong
  ngân sách được đo; Klipper không shutdown; test integration tái hiện được.

### R-002 — Reference offset và station envelope

- Bằng chứng: `_move_to_station()` luôn lấy station đã dạy rồi cộng
  `configured_offset(tool)`. Nếu reference tool có offset khác zero, chính
  reference cũng bị cộng lại khi quay về station. Target chỉ được kiểm tra từng
  tool sau khi calibration đã bắt đầu.
- Tác động: lệch camera/switch, lỗi ngoài giới hạn như `Y target ... outside`,
  hoặc phép đo dừng giữa chừng sau khi đã heat/toolchange.
- Giảm thiểu hiện tại: target cuối cùng qua `_validate_position()` và fail trước
  motion đó; report không tự áp offset.
- Giải pháp: preflight mọi tool/station trước khi heat; xác nhận reference
  offset zero trong giai đoạn hiện tại; kiểm tra cả vòng camera ±0,5 mm,
  correction envelope, Z clearance và switch probe depth. Về sau có thể chuẩn
  hóa station về nozzle/G-code coordinates để hỗ trợ reference non-zero.
- Đóng khi: test unit cho offset dấu ±, test boundary và HIL với station gần
  min/max đều fail sớm trước heater/toolchange; UI chỉ rõ cách sửa.

### R-003 — Recovery khi motion/toolchange/probe lỗi

- Bằng chứng: `_run_z_probe()` chỉ quay lại start sau probe thành công;
  `_calibrate_all()` nuốt mọi exception khi chọn lại original tool; `_guard()`
  cũng nuốt lỗi restore G-code state.
- Tác động: nozzle có thể dừng thấp, tool cuối vẫn gắn, hoặc lỗi khôi phục bị che
  bởi thông báo phép đo ban đầu.
- Giải pháp: một recovery state machine có thứ tự rõ: ngừng đo → retract nếu
  Klipper còn ready → heater cleanup → restore original tool → restore G-code
  state; giữ cả primary và cleanup errors trong status/result.
- Đóng khi: fault injection ở từng bước chứng minh không che lỗi gốc, thực hiện
  được recovery hợp lệ và báo chính xác phần nào chưa khôi phục.

### R-004 — Heater cleanup và capability

- Bằng chứng: `M104 Tn`/`M109` giả định macro/tool mapping tương thích; cleanup
  chỉ cảnh báo nếu `M104 Tn S0` lỗi. Mọi tool được preheat song song theo yêu
  cầu hiện tại.
- Tác động: heater có thể còn target, một số dock/tool không an toàn khi nóng,
  hoặc calibration treo ở wait trên phần cứng có macro khác.
- Giảm thiểu hiện tại: mặc định 150 °C theo Axiscope, cleanup nằm trong
  `finally`, máy đang printing/paused bị chặn và `TEMP=0` tồn tại.
- Giải pháp: capability/preflight heater, timeout/telemetry rõ, xác nhận tất cả
  target đã về 0 và escalated error nếu cleanup không đạt. Giữ workflow tự động
  nhưng cho profile phần cứng opt-in ở nơi thật sự không thể tự phát hiện.
- Đóng khi: HIL gồm missing heater, heater timeout, toolchange fail và cleanup
  fail; mọi case có trạng thái cuối được chứng minh.

### R-005 — Gate detector/transform chưa đủ

- Bằng chứng: transform kiểm tra rank/condition/residual nhưng không kiểm tra
  biên độ pixel cho chuyển động 0,5 mm; runtime chọn candidate tốt nhất mà không
  có confidence floor; ba frame giống nhau có thể là camera bị freeze.
- Tác động: transform có scale phi thực tế hoặc một vật thể ổn định khác được
  nhận là nozzle. Max-step 0,6 mm/max-distance 2 mm giới hạn motion nhưng không
  đảm bảo kết quả đúng.
- Giải pháp: gate sensitivity từ chính sample, holdout/return-to-center check,
  freshness evidence, ambiguity margin và uncertainty theo run. Threshold chỉ
  được chốt từ corpus/HIL, không thêm “magic number” chưa đo.
- Giảm thiểu `v3.3.0-rc1`: runtime từ chối nhiều candidate khác vị trí;
  transform schema 2 thêm leave-one-out, sensitivity/uncertainty; correction
  bắt buộc payload hữu hạn và tính uncertainty vào acceptance; centering dừng
  khi frame sau move không đổi quá noise floor. Có regression synthetic nhưng
  chưa có corpus/HIL. Evidence code: `b94876d`; xem
  [`DETECTION_DESIGN.md`](DETECTION_DESIGN.md).
- Đóng khi: corpus có frozen/distractor/blur/scale cực đoan bị từ chối và bộ ảnh
  hợp lệ không regression theo tiêu chí đã phê duyệt.

### R-006 — Thiếu bằng chứng đa phần cứng

- Bằng chứng: detector test dùng hình tròn tổng hợp; core Klipper coverage 32%;
  chưa có test với camera/nozzle/ánh sáng thật hoặc full Klipper process.
- Tác động: pass unit test nhưng sai trên camera khác, nozzle bẩn, phản xạ, tool
  count lớn hoặc toolchanger API khác.
- Giải pháp: versioned image corpus không chứa dữ liệu nhạy cảm, replay test,
  simulator/fakes cho Klipper và HIL matrix có raw run history.
- Đóng khi: release evidence chứa corpus ID, hardware IDs ẩn danh, số vòng lặp,
  repeatability và fault cases; không chỉ ghi “đã thử”.

### R-007 — Deployment chưa transactional

- Bằng chứng: installer thay nhiều file/service theo từng bước; không tự rollback
  toàn bộ khi bước sau lỗi. Uninstaller không phục hồi các regular file Klipper
  đã backup. Health check cuối chưa xác nhận API và Klipper object.
- Tác động: cài đặt dở dang, service/symlink/config không cùng phiên bản hoặc
  uninstall để lại Klipper không khởi động ở lần restart sau.
- Giải pháp: preflight đầy đủ trước write, manifest thay đổi, staging, commit
  hoặc rollback theo thứ tự; post-install health; restore drill cho upgrade và
  uninstall.
- Đóng khi: test trong VM/container cho fresh install, upgrade, failure ở từng
  bước, uninstall và restore file cũ đều pass.

### R-008 — Dependency và CI

- Bằng chứng: requirements dùng range rộng; installer nâng pip và resolve lại;
  repository chưa có lock/hash, dev requirements, CI hay Python/architecture
  matrix.
- Tác động: hai máy cài cùng tag có thể nhận dependency khác; upstream release
  mới có thể phá ARM/Python cũ.
- Giải pháp: chốt minimum Python/OS, constraints có hash hoặc release lock theo
  platform, CI unit/lint/audit/syntax, Dependabot/Renovate theo PR có test.
- Đóng khi: cài từ release được tái lập trên matrix đã công bố và update
  dependency luôn đi qua CI/HIL phù hợp.

### R-009 — State, migration và lịch sử

- Bằng chứng: schema không hỗ trợ migration; state lỗi bị bỏ qua trong RAM; kết
  quả mới ghi đè file cũ; atomic rename chưa fsync thư mục; không có manifest
  backup tự động trước setup/calibrate/update.
- Tác động: mất calibration học, khó so độ lặp/drift, hoặc setup mới ghi đè dữ
  liệu cũ trước khi người dùng kịp khôi phục.
- Giải pháp: backup-on-write có retention, migration có version/test, quarantine
  file lỗi, append-only run history và export gọn cho support.
- Đóng khi: migration/rollback qua ít nhất hai schema, power-loss simulation và
  restore drill đều có bằng chứng.

### R-010 — Camera resource bounds

- Bằng chứng: HTTP giới hạn 12 MiB dữ liệu nén nhưng không giới hạn số pixel sau
  decode; `cv2.VideoCapture.read()` không áp timeout từ `CameraSource.timeout`.
- Tác động: RTSP/device treo worker hoặc ảnh bất thường gây CPU/RAM cao trên SBC.
- Giải pháp: backend capture có deadline/reopen, giới hạn dimension/pixel trước
  pipeline, đo CPU/RSS và learned ROI ở runtime.
- Giảm thiểu `v3.3.0-rc1`: giới hạn HTTP nén 12 MiB và decode 16 MP; đặt
  `OPENCV_IO_MAX_IMAGE_PIXELS` trước import OpenCV; nguồn mạng truyền open/read
  timeout ở `VideoCapture.open`. Timeout này phụ thuộc backend chính thức, local
  device hang/reconnect và memory/RSS thật vẫn chưa được chứng minh. Evidence
  code: `b94876d`.
- Đóng khi: stream treo, reconnect, ảnh quá lớn và camera mất giữa job đều kết
  thúc có giới hạn, không làm service mất đáp ứng.

### R-011 — Contract toolchanger

- Bằng chứng: adapter hỗ trợ vài dạng status/get_offset nhưng fallback có thể
  nuốt lookup error và trả zero; test chỉ dùng fake nhỏ.
- Tác động: approach sai trên fork/version khác dù toolchange vẫn thành công.
- Giải pháp: contract test với các revision hỗ trợ, fail-closed khi không đọc
  được offset và compatibility matrix theo commit/tag.
- Đóng khi: matrix định nghĩa rõ supported/unsupported và CI integration test
  chạy với fixture API thật của từng dòng hỗ trợ.

### R-012 — Quyền sử dụng và governance

- Bằng chứng: repository public hiện chưa có root `LICENSE`.
- Tác động: người khác không biết quyền dùng/sửa/phân phối; khó nhận đóng góp và
  đóng gói release.
- Giải pháp: chủ repository chọn license sau khi kiểm tra nguồn gốc code và
  license dependency/submodule; thêm notice nếu cần. Không tự chọn license thay
  chủ sở hữu.
- Đóng khi: file license và policy đóng góp được chủ sở hữu phê duyệt.

## Rủi ro mức P2/P3

### R-013 — Configure race

Baseline `ServiceState.configure()` kiểm tra `active_job`, nhả lock để
mở/capture camera, rồi mới lock và swap; request khác có thể start job bằng
camera cũ trong cửa sổ đó. `v3.3.0-rc1` thêm trạng thái `configuring`, chặn
job/transform mutation, chỉ swap sau first-frame validation và giữ runtime cũ
nếu fail. Barrier concurrency test và failure cleanup test đã pass; giữ trạng
thái `Mitigating` cho đến khi nhánh được review/merge. Evidence code:
`b94876d`.

### R-014 — API exposure

Service an toàn hơn khi bind `127.0.0.1`, nhưng người dùng có thể override host
ra LAN trong khi API không authentication và cho reconfigure camera. Cần từ
chối non-loopback mặc định, hoặc yêu cầu explicit insecure acknowledgement và
document reverse proxy/auth. Không bao giờ khuyến nghị port-forward trực tiếp.

### R-015 — Observability

Result chưa có run ID, phase, duration, cleanup status, software/dependency
fingerprint hoặc raw sample summary. Log file chưa có rotation do ToolVision
quản lý. Cần structured result/event và support bundle có redaction.

### R-016 — Version drift

Version đang lặp ở Klippy, server fallback, package và test. Chuyển sang một
nguồn release được tạo tại build/install; thêm contract test so mọi nơi trước
tag. `v3.3.0-rc1` đã thêm contract test cho ba runtime source nhưng chưa hợp
nhất thành một nguồn build-time, nên rủi ro mới chỉ ở `Mitigating`.

### R-017 — Host runtime mất sau restart

Host service giữ camera/detector/transform trong RAM. Baseline chỉ configure khi
`TV_SETUP_CAMERA`; sau Moonraker update hoặc service restart, station vẫn có
trong Klippy state nhưng host trống, làm calibration XY fail muộn sau khi đã có
thể heat/toolchange. `v3.3.0-rc1` rehydrate host từ state trước mọi heat hoặc
toolchange của mode XY, đồng thời fail sớm với transform schema cũ. Unit test đã
kiểm tra thứ tự trong `b94876d`; còn cần HIL service-restart scenario trước khi
đóng.

## Quy trình cập nhật register

1. Tạo issue có ID rủi ro và link bằng chứng.
2. Chuyển `Open` → `Mitigating` khi đã có người chịu trách nhiệm và test tái
   hiện.
3. PR phải ghi ảnh hưởng đến safety/data/deployment và tiêu chí nghiệm thu.
4. Chỉ chuyển `Closed` sau khi release evidence/HIL phù hợp đã lưu.
5. Nếu chấp nhận rủi ro, ghi người phê duyệt, lý do, phạm vi và ngày xem lại;
   không dùng `Accepted` như cách bỏ qua.
