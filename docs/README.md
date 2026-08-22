# Trung tâm tài liệu ToolVision

Thư mục này là nguồn chỉ dẫn kỹ thuật và vận hành của ToolVision. Tài liệu được
chia theo mục đích để một thay đổi không bị lẫn giữa mô tả hiện trạng, quyết
định kiến trúc và kế hoạch tương lai.

Baseline khi khởi tạo bộ tài liệu: `v3.2.1`, commit `42202a2`, ngày
2026-08-22. Mốc khôi phục trước audit là
`backup/pre-project-audit-20260822`. Trước khi handbook được commit, runtime đã
lên `v3.2.2` tại `dd92a05`; delta này chỉ tổ chức lại generated data/backup và
được giữ ở tag `backup/pre-governance-docs-20260822`.

## Đọc theo vai trò

### Người dùng máy in

1. [`../README.md`](../README.md): cài đặt và workflow bốn lệnh.
2. [`OPERATIONS.md`](OPERATIONS.md): vận hành bình thường và xử lý sự cố.
3. [`BACKUP_RESTORE.md`](BACKUP_RESTORE.md): sao lưu và khôi phục dữ liệu.

### Người phát triển

1. [`../AGENTS.md`](../AGENTS.md): chỉ dẫn tự nạp và các quy tắc bắt buộc cho
   mọi agent làm việc trong repository.
2. [`ARCHITECTURE.md`](ARCHITECTURE.md): các invariant về dấu offset, chuyển
   động và ranh giới process.
3. [`CODE_CONVENTIONS.md`](CODE_CONVENTIONS.md): quy ước viết code, xử lý lỗi,
   version, logging và cách chú thích.
4. [`DEVELOPMENT.md`](DEVELOPMENT.md): cách chia việc, tạo nhánh, review và
   Definition of Done.
5. [`TESTING.md`](TESTING.md): chiến lược unit, integration, image corpus và
   Hardware-in-the-Loop (HIL).
6. [`RISK_REGISTER.md`](RISK_REGISTER.md): rủi ro đang mở và tiêu chí đóng.
7. [`PROJECT_PLAN.md`](PROJECT_PLAN.md): thứ tự triển khai các workstream.

### Người bảo trì/phát hành

1. [`DATA_AND_STORAGE.md`](DATA_AND_STORAGE.md): nơi lưu config, state, result,
   log và chính sách migration.
2. [`RELEASE.md`](RELEASE.md): checklist phát hành, canary và rollback.
3. [`COMPATIBILITY.md`](COMPATIBILITY.md): môi trường đã quan sát và ma trận cần
   chứng minh.
4. [`../SECURITY.md`](../SECURITY.md): mô hình bảo mật và cách báo lỗi.

## Loại tài liệu và mức thẩm quyền

| Tài liệu | Loại | Quy tắc |
|---|---|---|
| `ARCHITECTURE.md` | normative | Code không được phá invariant nếu chưa có ADR/review |
| `RISK_REGISTER.md` | living register | Mọi rủi ro phải có owner, trạng thái và bằng chứng đóng |
| `PROJECT_PLAN.md` | living plan | Chỉ mô tả thứ tự và gate; không thay thế issue/PR |
| `AUDIT_2026-08-22.md` | snapshot | Không sửa kết luận lịch sử; audit mới tạo file mới |
| `OPERATIONS.md`, `RELEASE.md` | runbook | Phải được kiểm tra lại khi command/path/service đổi |
| `DATA_AND_STORAGE.md` | contract | Mọi thay đổi schema/path phải cập nhật cùng commit |
| `CODE_CONVENTIONS.md` | normative | Code/comment mới phải tuân thủ; ngoại lệ cần ghi trong review |

`AGENTS.md` ở root là điểm vào tự động cho Codex. Các file trong `docs/` không
tự được nạp chỉ vì nằm trong thư mục; `AGENTS.md` yêu cầu agent đọc đúng tài
liệu theo loại công việc để tránh nhồi toàn bộ handbook vào context.

## Tự nạp khi mở phiên mới

Chỉ cần mở repository này làm workspace/current directory trong một phiên Codex
mới. Codex đọc `AGENTS.md` từ root trước khi bắt đầu công việc; không cần chạy
script bootstrap. Nếu dùng Codex CLI và muốn kiểm tra đúng nguồn chỉ dẫn đã nạp:

```bash
codex --cd /path/to/Tool-Vision --ask-for-approval never \
  "List the instruction files you loaded, then summarize them."
```

Codex xây lại instruction chain một lần cho mỗi run/session mới. Sau khi sửa
`AGENTS.md`, hãy mở phiên mới để kiểm tra. Thư mục `.agent/` không phải tên tự
động được khám phá mặc định; chỉ dùng tên khác khi đã cấu hình fallback. Xem
[tài liệu chính thức về `AGENTS.md`](https://learn.chatgpt.com/docs/agent-configuration/agents-md.md).

## Quy tắc cập nhật tài liệu

- Đổi lệnh G-code hoặc workflow người dùng: cập nhật `README.md` và
  `OPERATIONS.md`.
- Đổi dấu offset, chuyển động, detector, transform hoặc process boundary: cập
  nhật `ARCHITECTURE.md`, test regression và một ADR nếu thay đổi invariant.
- Đổi file/path/schema: cập nhật `DATA_AND_STORAGE.md`, migration và quy trình
  backup/restore.
- Đổi installer, systemd hoặc Moonraker: cập nhật `OPERATIONS.md`,
  `BACKUP_RESTORE.md`, `RELEASE.md` và test upgrade/uninstall.
- Phát hiện rủi ro mới: thêm ID vào `RISK_REGISTER.md` trước khi sửa; commit/PR
  đóng rủi ro phải trỏ lại ID đó.
- Không xóa bằng chứng audit hoặc release cũ. Tài liệu lịch sử là một phần của
  khả năng truy vết.

## Mẫu dùng lại

- [`templates/CHANGE_PLAN.md`](templates/CHANGE_PLAN.md): kế hoạch cho một thay
  đổi có rủi ro.
- [`templates/RELEASE_EVIDENCE.md`](templates/RELEASE_EVIDENCE.md): hồ sơ kiểm
  thử cho mỗi release.
- [`templates/INCIDENT_REPORT.md`](templates/INCIDENT_REPORT.md): ghi nhận sự cố
  mà không làm mất timeline.
- [`adr/0000-template.md`](adr/0000-template.md): mẫu Architecture Decision
  Record.

Tài liệu mô tả giải pháp chưa triển khai phải ghi rõ `Đề xuất` hoặc `Planned`.
Không được mô tả một kiểm tra, cơ chế backup hay khả năng tương thích là đã có
nếu chưa có test hoặc bằng chứng HIL tương ứng.
