# ADR-0001 — Kết quả mặc định là report-only

- Status: Accepted
- Date: 2026-08-21
- Risk IDs: R-006, R-009

## Context

ToolVision đo offset cơ khí bằng camera/switch trên phần cứng khác nhau. Kết quả
cần được kiểm tra độ lặp và xác nhận bằng phương pháp độc lập trước khi trở thành
offset sản xuất.

## Decision

Calibration chỉ report và ghi result JSON. Lõi không gọi
`SET_TOOL_PARAMETER`, `SAVE_TOOL_PARAMETER` hoặc `SAVE_CONFIG`.

## Consequences

- Một false measurement không tự thay cấu hình đang in.
- Người dùng còn một bước review/apply thủ công.
- Mọi tính năng “Apply/Save” tương lai là thay đổi safety cấp cao, cần ADR mới,
  backup, validation và rollback.

## Verification

Contract test quét active extension để bảo đảm ba command ghi production offset
không xuất hiện; HIL xác nhận config không đổi sau calibration.
