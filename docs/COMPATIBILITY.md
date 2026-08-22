# Ma trận tương thích

## Cách đọc

- `Observed`: đã thấy chạy/smoke-test trên một máy, chưa đủ thành cam kết chung.
- `Tested`: có test lặp và release evidence.
- `Supported`: maintainer cam kết xử lý regression trong phạm vi đã ghi.
- `Unknown`: chưa có bằng chứng; không suy diễn từ một version gần giống.

Hiện dự án mới có môi trường `Observed`, chưa công bố matrix `Supported`.

## Môi trường pilot đã quan sát

| Thành phần | Giá trị | Trạng thái |
|---|---|---|
| OS | Debian 12 (bookworm), aarch64 | Observed |
| Python host venv | 3.11.2 | Observed |
| Klipper | `60fc7aa67a8da9abb43a2bad825d4992294ebf3f` | Observed |
| Moonraker | `d5ee17128bb88434aacdab90c2e9e990e2b64e4a` | Observed |
| klipper-toolchanger-easy | `e881fe40949a3999b0d63f59c22df589474eae9b` | Observed |
| ToolVision | `v3.2.1` | Observed |
| Flask | 3.1.3 | Observed |
| NumPy | 2.4.6 | Observed |
| OpenCV headless | 4.14.0.94 | Observed |
| Waitress | 3.0.2 | Observed |

Máy pilot đã xác nhận updater Moonraker, host health và Klipper ready. Audit
2026-08-22 không chạy lại calibration/motion/heat.

## Nguồn logic đã ghim

| Project | Revision | Vai trò |
|---|---|---|
| Axiscope | `9a1a9efe3cfa6dc1e816acaaea87f8ac513282f6` | probe primitive/workflow Z và dấu trigger delta |
| kTAMV | `72421f2d54da0de8701c4f84449c6e6b7d060301` | pattern 10 điểm, centering và dấu raw XY |

Submodule dùng cho phát triển/đối chiếu, không phải runtime dependency trên máy.

## Điều kiện runtime hiện tại

- Linux có systemd, Git, sudo, Python 3 và khả năng tạo venv.
- Klipper + Moonraker + toolchanger object.
- `tools_calibrate.py` từ dòng klipper-toolchanger tương thích.
- Camera upward cho XY; snapshot/MJPEG/OpenCV source theo code hiện tại.
- Contact switch và `pin` hợp lệ nếu đo Z.
- Moonraker data path/layout tương thích installer hoặc được override rõ.

## Matrix cần xây trong WS0/WS3

| Trục | Case tối thiểu cần test |
|---|---|
| Python | minimum được chốt, current stable |
| CPU/OS | Debian ARM64 pilot, một Linux x86_64 test image |
| Klipper | pinned supported revisions, current candidate |
| Moonraker | version có `moonraker.asvc`, N-1/current |
| Toolchanger | upstream viesturz và fork được tuyên bố hỗ trợ |
| Tool count | 2, nhiều hơn 2, số tool không liên tục |
| Camera | snapshot, MJPEG, `/dev/video`, RTSP nếu giữ support |
| Resolution | thấp hợp lệ, phổ biến, native high-resolution |
| Switch | normal-open/normal-closed, invert/pull-up variants |
| Install | fresh, upgrade N-1, rollback, uninstall |

Không ghi “supported” vào README trước khi hàng tương ứng có release evidence.

## Chính sách thay đổi compatibility

- Nâng minimum Python/OS hoặc bỏ backend camera là breaking change và cần
  changelog/migration.
- Update upstream toolchanger phải chạy contract tests và đối chiếu dấu offset.
- Dependency update không được merge chỉ vì resolver thành công trên một máy.
- Mỗi release evidence ghi chính xác revision đã test, không chỉ tên project.
