# Changelog

Định dạng dựa trên Keep a Changelog; version dùng Semantic Versioning theo
[`docs/RELEASE.md`](docs/RELEASE.md).

## Unreleased

### Documentation

- Thêm full-source audit 2026-08-22 và risk register.
- Thêm project roadmap, development workflow, testing/HIL strategy.
- Thêm operations, data/storage, backup/restore, compatibility và release
  runbook.
- Thêm contributing, security, ADR và các mẫu hồ sơ thay đổi/release/incident.
- Thêm `AGENTS.md` tự nạp cùng quy ước viết code/chú thích chi tiết.

Không có thay đổi logic đo trong mục Unreleased này.

## 3.2.2 — 2026-08-22

### Changed

- Chuyển state/result mặc định vào `printer_data/config/Tool-Vision/`.
- Installer di chuyển dữ liệu mặc định cũ có backup và giữ nguyên đường dẫn do
  người dùng khai báo tường minh.
- Gom backup install/uninstall vào
  `printer_data/config_backups/tool-vision/`.

## 3.2.1 — 2026-08-21

### Fixed

- Installer tự thêm exact service `tool-vision` vào Moonraker
  `moonraker.asvc`, có backup; uninstaller gỡ đúng entry đó.
- Kiểm tra sudo trước khi installer bắt đầu mutation để tránh cài dở trong
  terminal non-interactive.

### Verified

- Moonraker Update Manager đã nâng máy pilot từ 3.2.0 lên 3.2.1, restart host
  service/Klipper và giữ learned switch state.

## 3.2.0 — 2026-08-21

### Added

- Git checkout trở thành runtime do Moonraker quản lý.
- Moonraker Update Manager config, isolated venv requirements và managed
  service restart.
- Calibration tự preheat 150 °C, wait từng active tool và cleanup heater khi
  success/failure bình thường.

### Changed

- README mô tả cập nhật qua Mainsail/Fluidd và workflow nhiệt tự động.

## Lịch sử trước release tag

Các mốc trước 3.2.0 được giữ bằng Git history và backup tags. Chúng chưa có
release evidence chuẩn hóa; không suy diễn compatibility chỉ từ tên commit.
