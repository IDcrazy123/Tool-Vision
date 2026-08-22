# Quy trình phát triển

## Mục tiêu

Mọi thay đổi ToolVision phải nhỏ, truy vết được, có đường rollback và không thử
nghiệm trực tiếp trên máy đang in. Quy trình này áp dụng cả thay đổi thuật toán,
G-code, installer và tài liệu vận hành.

Khi mở phiên mới, Codex tự đọc [`../AGENTS.md`](../AGENTS.md). Người phát triển
và agent sau đó phải áp dụng [`CODE_CONVENTIONS.md`](CODE_CONVENTIONS.md), đặc
biệt các quy tắc về comment safety, error cleanup và tương thích Python.

## Trước khi bắt đầu

Một task chỉ `Ready` khi có:

- vấn đề hoặc yêu cầu cụ thể;
- Risk ID liên quan, hoặc lý do không liên quan safety/data/deployment;
- baseline commit và môi trường tái hiện;
- phạm vi file dự kiến;
- test sẽ chứng minh thay đổi;
- tác động đến state/schema/config/API;
- cách quay lại trạng thái trước thay đổi.

Dùng [`templates/CHANGE_PLAN.md`](templates/CHANGE_PLAN.md) cho task có motion,
heater, camera, migration hoặc installer.

## Backup bắt buộc

Trước thay đổi lớn:

1. worktree phải sạch;
2. tạo annotated tag `backup/pre-<topic>-YYYYMMDD-HHMMSS` tại commit hiện tại;
3. push tag lên remote;
4. sao lưu dữ liệu printer theo [`BACKUP_RESTORE.md`](BACKUP_RESTORE.md) nếu sẽ
   deploy/HIL;
5. ghi tag và backup path vào change plan.

Backup Git không thay thế backup state/config trên printer. Venv, Git checkout
và dependency cache là dữ liệu tái tạo được; config/state/result là dữ liệu cần
bảo vệ.

## Nhánh và commit

- `main` là nhánh tích hợp/release, không phát triển trực tiếp khi có thể dùng
  PR.
- Nhánh do Codex tạo dùng tiền tố `codex/`; nhánh người dùng có thể dùng
  `fix/`, `feature/`, `docs/` hoặc `release/`.
- Một branch giải quyết một mục tiêu; không trộn refactor style với sửa safety.
- Commit dùng động từ rõ: `fix:`, `feat:`, `test:`, `docs:`, `refactor:`.
- Không force-push `main`; không sửa tag release đã công bố.
- Thay đổi submodule phải là commit riêng, ghi upstream revision và lý do.

## Chu trình vertical slice

1. **Read:** đọc implementation, test, invariant và nguồn upstream liên quan.
2. **Reproduce:** thêm test hoặc log/evidence làm lỗi xuất hiện ổn định.
3. **Design:** viết behavior mong muốn, failure behavior và rollback.
4. **Implement:** sửa phạm vi nhỏ nhất, chú thích “vì sao” ở đoạn safety khó suy
   ra theo [`CODE_CONVENTIONS.md`](CODE_CONVENTIONS.md); không chú thích lại
   điều code đã nói rõ.
5. **Verify:** unit → integration → simulator → HIL theo mức rủi ro.
6. **Document:** cập nhật README/runbook/schema/risk/ADR trong cùng commit/PR.
7. **Release:** canary, evidence, tag, Moonraker update, theo dõi và rollback nếu
   gate fail.

## Quy tắc theo vùng mã

### Klipper extension

- Không đưa OpenCV/NumPy hoặc tác vụ chặn dài vào process Klipper.
- Mọi motion phải có preflight, limit check và recovery có trạng thái.
- Không nuốt lỗi restore; lưu primary error và cleanup errors riêng.
- Không thay dấu offset nếu chưa cập nhật invariant, test và ADR.
- Không tự ghi offset sản xuất trong một thay đổi không có ADR/safety review.

### Host service

- Serialize mutation camera/detector/transform.
- Mọi I/O phải có deadline và giới hạn tài nguyên.
- API lỗi dự kiến trả JSON ổn định; lỗi nội bộ không lộ credential/URL nhạy cảm.
- Camera test phải gồm snapshot, MJPEG và OpenCV backend được tuyên bố hỗ trợ.

### State và result

- Không đổi schema “tại chỗ”. Tăng version, viết migration và test downgrade/
  rollback behavior.
- Ghi backup/quarantine trước khi thay thế dữ liệu không tương thích.
- Không lưu credential vào result/support bundle.

### Installer/updater

- Preflight hết điều kiện có thể biết trước rồi mới write.
- Mọi file bị thay phải có manifest và bản sao phục hồi.
- Không báo thành công trước API health, Klipper ready và version parity.
- Fresh install, N-1 upgrade, interrupted install và uninstall đều là test case.

## Review checklist

Reviewer phải trả lời:

- Có motion/heat/toolchange mới hoặc đổi thứ tự không?
- Failure tại từng await/I/O/toolchange/probe để máy ở trạng thái nào?
- Có request đồng bộ trong Klipper reactor không?
- Target đã được kiểm tra cho tất cả tool trước khi bắt đầu chưa?
- State/config/result có tương thích ngược và backup không?
- Dấu offset có test độc lập không?
- Threshold mới đến từ dữ liệu nào?
- Dependency/path/service/version có bị lệch giữa installer và updater không?
- README/runbook/risk register/release evidence đã cùng sự thật với code chưa?

## Definition of Done

Một task chỉ `Done` khi:

- test tái hiện cũ fail và code mới pass;
- toàn bộ test suite pass;
- không giảm coverage vùng critical nếu chưa có lý do được review;
- test syntax/config/dependency phù hợp pass;
- HIL được chạy nếu thay motion, probe, heater, toolchange hoặc camera transport;
- docs và changelog được cập nhật;
- backup/rollback đã ghi và ít nhất dry-run hợp lệ;
- Risk ID được cập nhật bằng link commit/evidence;
- worktree sạch và remote branch/tag đã xác minh.

Không dùng “chạy được một lần trên máy của tôi” thay cho Definition of Done.
