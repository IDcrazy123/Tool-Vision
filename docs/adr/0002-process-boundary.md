# ADR-0002 — Tách motion Klipper và computer vision host

- Status: Accepted
- Date: 2026-08-21
- Risk IDs: R-001, R-010, R-014

## Context

OpenCV/NumPy và camera I/O có latency, CPU/RAM và dependency không phù hợp process
realtime Klipper. Host service không nên có quyền tự ra lệnh chuyển động.

## Decision

- Klippy extension sở hữu homing checks, limits, toolchange, heater, manual move
  và probe.
- Host service sở hữu camera discovery/capture, detector và transform.
- Host chỉ trả observation/correction; không gọi Moonraker để di chuyển máy.

## Consequences

- Dependency CV không làm nặng Klipper process.
- Ranh giới safety rõ và dễ mock/test.
- Transport giữa hai process phải được thiết kế không chặn reactor; HTTP đồng bộ
  hiện tại là risk R-001, không phải lý do hủy process boundary.

## Verification

Static contract và integration test bảo đảm host không có printer-motion call,
Klippy không import OpenCV/NumPy, transport fault không khóa reactor.
