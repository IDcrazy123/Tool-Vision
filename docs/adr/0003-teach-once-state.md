# ADR-0003 — Dạy fixture thay vì khai báo tọa độ/tuning trong `.cfg`

- Status: Accepted
- Date: 2026-08-21
- Risk IDs: R-002, R-005, R-009

## Context

Camera và switch được lắp ở vị trí khác nhau trên mỗi máy. Threshold, ROI,
rotation, pixel scale và tool list cũng phụ thuộc hardware/runtime. Bắt người
dùng nhập các giá trị này làm setup khó và dễ sai.

## Decision

Người dùng gắn reference tool, jog nozzle đến fixture và chạy một command setup.
ToolVision học station, detector và transform rồi lưu state ngoài Git. `.cfg`
chỉ giữ thông tin không thể suy ra an toàn như switch pin hoặc camera selector
khi discovery mơ hồ.

## Consequences

- Workflow ngắn, gần mục tiêu kTAMV/Axiscope.
- State trở thành dữ liệu quan trọng cần schema, backup, migration và hardware
  fingerprint.
- Không được “tự học” fixture bằng chuyển động mù. Người vận hành vẫn bảo đảm
  đường thẳng đứng/fixture an toàn.
- Preflight phải chứng minh station envelope cho mọi tool trước calibration.

## Verification

Config contract không có tuning bắt buộc; setup overwrite có test; state atomic,
migration/backup và HIL station envelope là release gate.
