# Lộ trình dự án ToolVision

Lộ trình ưu tiên safety và bằng chứng đo trước tính năng mới. Không gắn deadline
cứng khi chưa biết nguồn lực; mỗi phase chỉ được qua khi đạt exit gate.

## Mục tiêu sản phẩm

- Người dùng chỉ dạy vị trí camera/switch bằng cách jog reference nozzle rồi
  chạy một lệnh.
- Camera/detector/transform tự thích nghi trong giới hạn đã được kiểm chứng,
  không đẩy hàng loạt tham số OpenCV vào `.cfg`.
- Đo XYZ tương đối lặp lại được trên nhiều phần cứng.
- Mọi chuyển động, nhiệt và ghi dữ liệu đều fail-safe, truy vết và khôi phục
  được.
- Cập nhật bình thường qua Moonraker/Mainsail; không sửa code trực tiếp trên máy.
- Chưa tự áp offset sản xuất cho đến khi measurement validity và rollback đạt
  gate riêng.

## Nguyên tắc ưu tiên

1. P0/P1 safety trước UX và tối ưu tốc độ.
2. Viết test tái hiện trước khi sửa một rủi ro.
3. Một vertical slice nhỏ: code + test + docs + migration/rollback.
4. Không lấy một máy pilot làm bằng chứng “mọi phần cứng”.
5. Không thêm tham số người dùng nếu có thể đo/học; nếu không thể tự suy ra,
   phải ghi rõ invariant phần cứng thay vì đoán.
6. Report-only là mặc định cho đến một ADR mới được phê duyệt.

## Workstream

| ID | Nội dung | Risk |
|---|---|---|
| WS0 | Governance, version, license, CI foundation | R-012, R-016 |
| WS1 | Klipper realtime, motion, toolchange, heater safety | R-001–R-004, R-011 |
| WS2 | Camera/detector/transform validity và resource bounds | R-005, R-006, R-010, R-013 |
| WS3 | Installer, updater, dependency, state/backup/rollback | R-007–R-009, R-014 |
| WS4 | UX, progress, report history, support bundle | R-015 |

## Phase 0 — Baseline và governance

Deliverables:

- Bộ tài liệu audit/risk/workflow/runbook/release hiện tại.
- Issue map theo Risk ID; nhãn `P0`–`P3`, `safety`, `measurement`, `deployment`.
- Chủ repository quyết định license.
- Chốt minimum Python/Klipper/Moonraker/toolchanger ban đầu.
- CI tối thiểu: unit, compile, safety lint, shell syntax, dependency audit và
  link/config contract.
- Một nguồn version duy nhất và `CHANGELOG.md` theo release.

Exit gate:

- Main được bảo vệ bằng PR/check; không còn release thủ công thiếu evidence.
- R-012 và R-016 đóng; R-008 ít nhất ở `Mitigating`.

## Phase 1 — Safety/realtime core

Thứ tự triển khai:

1. R-001: test endpoint delay/hang và thiết kế transport không chặn reactor.
2. R-002: preflight tất cả tool/station/envelope trước heater hoặc toolchange.
3. R-003: recovery state machine và bảo toàn primary + cleanup error.
4. R-004: heater capability, timeout, verify-off và cleanup result.
5. R-011: toolchanger contract tests, fail-closed offset lookup.

Deliverables:

- `TV_VALIDATE` hoặc preflight nội bộ dùng chung cho setup/calibrate.
- Trạng thái phase rõ: `preflight`, `heating`, `selecting`, `moving`, `probing`,
  `cooling`, `restoring`.
- Không có `except/pass` ở recovery mà không ghi trạng thái.
- Fault-injection suite không cần máy thật cho phần lớn nhánh lỗi.

Exit gate:

- P0 R-001 đóng.
- Mọi P1 WS1 có test tái hiện và không còn lỗi làm calibration bắt đầu một phần
  khi preflight đã biết chắc sẽ fail.
- HIL chứng minh tool/heater/G-code state cuối ở trạng thái đã định nghĩa cho cả
  success và failure.

## Phase 2 — Measurement validity

Thứ tự triển khai:

1. Xây corpus ảnh thật có metadata nhưng không chứa địa chỉ/credential.
2. Replay baseline để đo false positive/false reject theo camera/nozzle/light.
3. Thêm transform sensitivity, holdout và frozen-frame/freshness checks.
4. Thêm uncertainty/raw sample summary cho XY và Z.
5. Chạy repeatability study trên nhiều máy; chốt threshold từ dữ liệu, không từ
   trực giác.

Deliverables:

- Dataset versioned ngoài Git nếu lớn, có manifest/checksum/license.
- Bộ test blur, glare, dirty nozzle, distractor, stale frame, rotation, scale,
  lens angle và resolution.
- Kết quả từng run giữ raw sample summary và fingerprint calibration.
- Cảnh báo drift khi camera/switch/reference thay đổi đáng kể.

Exit gate:

- R-005, R-006 và R-010 đóng theo evidence.
- Có chuẩn độ lặp được phê duyệt cho từng lớp phần cứng hỗ trợ.
- Không có regression vượt ngân sách đã ghi trong release evidence.

## Phase 3 — Deployment và data reliability

Deliverables:

- Installer transactional: preflight, manifest, stage, commit/rollback, health.
- Uninstaller phục hồi đúng file đã thay hoặc dừng với hướng dẫn rõ.
- Constraints/lock tái lập theo Python/architecture hỗ trợ.
- State migration/quarantine/backup-on-write và append-only run history.
- Backup/restore script có `--dry-run`, checksum, retention và restore drill.
- Update/rollback được test qua Moonraker từ ít nhất release N-1.

Exit gate:

- R-007, R-008 và R-009 đóng.
- Fresh install, upgrade, interrupted upgrade, uninstall và restore đều có test
  tự động hoặc evidence HIL bắt buộc.

## Phase 4 — UX vận hành

Deliverables:

- Status/progress dễ hiểu trong Mainsail, lỗi có action cụ thể.
- Preview/support bundle có redaction.
- Lịch sử run và so sánh độ lặp/drift.
- Wizard giữ workflow “jog rồi một lệnh”, không lộ tuning mặc định.
- Tách “kết quả đo” và “đề xuất offset”; áp dụng vẫn là bước có xác nhận và
  backup.

Exit gate:

- Người mới hoàn tất setup/calibrate theo usability test mà không sửa tham số
  detector.
- Support có thể chẩn đoán từ một bundle mà không cần thu thập credential.

## Phase 5 — Xem xét áp offset có kiểm soát

Chỉ bắt đầu sau Phase 1–4. Cần ADR riêng trả lời:

- format offset chuẩn cho từng toolchanger;
- cách backup/rollback config;
- validation print/first-layer;
- quyền xác nhận của người dùng;
- chống áp kết quả stale, low-confidence hoặc khác hardware fingerprint.

Mặc định hiện tại vẫn report-only. Không coi “thêm nút Save” là một thay đổi UX
nhỏ; đó là thay đổi safety/data cấp cao.

## Nhịp làm việc cho từng task

```text
Risk/requirement
  -> evidence + reproduction
  -> change plan + rollback
  -> test fail trước sửa
  -> implementation nhỏ
  -> unit/integration
  -> simulator/HIL nếu có motion/heat/camera
  -> docs + release evidence
  -> canary
  -> release/monitor/close risk
```

Mỗi task dùng [`templates/CHANGE_PLAN.md`](templates/CHANGE_PLAN.md). Mỗi release
dùng [`templates/RELEASE_EVIDENCE.md`](templates/RELEASE_EVIDENCE.md).
