# Architecture Decision Records

ADR ghi quyết định khó đảo ngược hoặc ảnh hưởng invariant. ADR đã `Accepted`
không bị sửa để viết lại lịch sử; thay đổi quyết định bằng ADR mới có liên kết
`Supersedes`.

| ADR | Trạng thái | Quyết định |
|---|---|---|
| [`0001-report-only.md`](0001-report-only.md) | Accepted | Kết quả mặc định không tự áp offset |
| [`0002-process-boundary.md`](0002-process-boundary.md) | Accepted | Motion ở Klipper, computer vision ở host |
| [`0003-teach-once-state.md`](0003-teach-once-state.md) | Accepted | Fixture được dạy và lưu ngoài `.cfg` |

Dùng [`0000-template.md`](0000-template.md) cho quyết định mới.
