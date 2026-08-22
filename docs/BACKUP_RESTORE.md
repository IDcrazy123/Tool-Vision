# Backup và khôi phục

## Mục tiêu

Backup phải trả lời được ba câu hỏi:

1. Code nào đang chạy?
2. Config/state/result nào đi cùng code đó?
3. Đã từng kiểm tra restore thành công chưa?

Một thư mục copy chưa có checksum hoặc chưa restore drill chỉ là bản sao, chưa
phải backup đã xác nhận.

## Khi nào bắt buộc backup

- trước rewrite/refactor lớn;
- trước thay schema/path/dependency/installer/systemd;
- trước update release có motion/heater/camera behavior mới;
- trước dạy lại camera/switch;
- trước áp offset đo vào cấu hình sản xuất;
- ngay sau một setup/HIL tốt cần giữ làm baseline;
- trước thu thập/sửa file khi xử lý incident.

## Backup code vào một thư mục local

Tạo một thư mục `.local-backups/<topic>-<timestamp>/` trong checkout. Pattern
này nằm trong `.gitignore`, vì vậy backup công việc không được push lên GitHub.
Tại worktree sạch:

```bash
git status --short --branch
backup_dir=".local-backups/pre-<topic>-YYYYMMDD-HHMMSS"
mkdir -p "${backup_dir}"
git bundle create "${backup_dir}/repository.bundle" --all
git rev-parse HEAD > "${backup_dir}/BASELINE.txt"
git status --short --branch > "${backup_dir}/STATUS.txt"
git bundle verify "${backup_dir}/repository.bundle"
```

Nếu worktree có thay đổi hợp lệ cần giữ, copy đúng các file đó vào cùng thư mục
backup trước khi sửa tiếp và ghi rõ chúng trong change plan. Không dùng GitHub
branch/tag làm kho backup công việc. Remote chỉ giữ commit/PR và semantic
release tag; xem ADR-0004.

## Backup dữ liệu printer

Chạy khi máy idle. Đoạn lệnh sau chỉ copy file hiện có vào thư mục timestamp;
kiểm tra đường dẫn trước khi dùng trên hệ không theo layout `printer_data`.

```bash
set -Eeuo pipefail
install_user="$(id -un)"
user_home="$(getent passwd "${install_user}" | cut -d: -f6)"
printer_data="${user_home}/printer_data"
stamp="$(date +%Y%m%d-%H%M%S)"
backup_root="${printer_data}/config_backups/tool-vision/manual-${stamp}"

# Thu cả layout hiện tại và các path legacy nếu migration chưa hoàn tất.
install -d -m 0750 "${backup_root}"
for source_path in \
  "${printer_data}/config/tool_vision.cfg" \
  "${printer_data}/config/Printer-Setup" \
  "${printer_data}/config/Tool-Vision" \
  "${printer_data}/config/tool_vision_state.json" \
  "${printer_data}/config/tool_vision_results.json" \
  "${printer_data}/config/printer.cfg" \
  "${printer_data}/config/moonraker.conf" \
  "${printer_data}/moonraker.asvc"; do
  if [ -e "${source_path}" ]; then
    cp -a -- "${source_path}" "${backup_root}/"
  fi
done

git -C "${user_home}/Tool-Vision" rev-parse HEAD > "${backup_root}/tool-vision.commit"
(
  cd "${backup_root}"
  find . -type f ! -name SHA256SUMS -print0 | sort -z | \
    xargs -0 sha256sum > SHA256SUMS
)
printf 'Backup: %s\n' "${backup_root}"
```

Nếu `tool_vision.cfg` có camera URL chứa credential, backup phải có permission
hạn chế và bản gửi support phải redaction.

## Kiểm tra backup

```bash
cd /đường/dẫn/backup
sha256sum --check SHA256SUMS
for json_path in \
  Printer-Setup/tool_vision_state.json \
  Printer-Setup/tool_vision_results.json \
  Tool-Vision/tool_vision_state.json \
  Tool-Vision/tool_vision_results.json \
  tool_vision_state.json \
  tool_vision_results.json; do
  if [ -f "${json_path}" ]; then
    python3 -m json.tool "${json_path}" >/dev/null
  fi
done
```

Loop bỏ qua file không tồn tại, nhưng cố ý trả lỗi nếu file hiện có mà parse
fail. Khi đó backup phải được đánh dấu không hợp lệ và điều tra trước thay đổi
tiếp theo.

## Chính sách retention

- Local: tối thiểu 10 snapshot gần nhất hoặc nhiều hơn nếu dung lượng cho phép.
- Giữ vô thời hạn snapshot trước migration/schema và mọi release evidence.
- Off-device: ít nhất một bản config/state/result quan trọng ngoài SBC.
- Code: bundle/file backup trong thư mục local bị Git ignore; semantic release
  tag trên remote không thay thế backup công việc.
- Không backup venv làm nguồn khôi phục chính; dependency phải tái dựng từ
  constraints/release.

Xóa backup cũ là thao tác riêng có review; không đặt lệnh xóa recursive vào
installer/update path.

## Khôi phục state/result/config

Chỉ làm khi máy idle và đã tạo thêm backup của trạng thái hiện tại.

1. Xác minh `SHA256SUMS`, baseline commit và schema.
2. Dừng calibration; nếu thay extension config/state, dừng Klipper theo runbook
   của máy.
3. Copy file cần thiết vào đúng path, giữ owner/mode.
4. Parse JSON/config trước restart.
5. Restart service/Klipper, chạy `TV_STATUS` và validation không chuyển động nếu
   có.
6. Không chạy calibration đầy đủ cho đến khi station/hardware vẫn khớp.

Không khôi phục mù quáng station từ máy khác: vị trí camera/switch là dữ liệu
gắn với phần cứng cụ thể.

## Rollback code

Ưu tiên theo thứ tự:

1. Nút rollback của Moonraker/Mainsail nếu release evidence đã kiểm thử đường đó.
2. Maintainer phát hành một commit revert trên `main`, rồi update bình thường
   qua Moonraker.
3. Chỉ trong incident cần cô lập, cài release đã biết tốt vào runtime song song
   theo procedure được review; không dùng `git reset --hard` tùy tiện trên máy.

Sau rollback:

- xác nhận updater, host health và Klipper cùng version;
- kiểm tra state schema có tương thích release cũ;
- restore state/config matching nếu migration không downgrade-safe;
- chạy smoke/HIL gate của release đó;
- ghi incident/release evidence.

## Restore drill

Ít nhất mỗi thay đổi schema/installer và định kỳ trước stable release:

1. Tạo backup mới.
2. Dựng môi trường test hoặc máy pilot idle.
3. Cài release N-1 và state tương ứng.
4. Upgrade lên N, xác minh.
5. Rollback code và restore data.
6. So checksum/file owner/service/API/Klipper state.
7. Ghi thời gian, lỗi và thao tác thủ công vào release evidence.

Backup không qua restore drill phải ghi `unverified`.

## Mốc backup đã tạo cho audit và migration

- Git tag: `backup/pre-project-audit-20260822`.
- Commit: `42202a295d4b28321afe5f047c59b4d367399fed`.
- Git tag trước khi thêm handbook/agent contract:
  `backup/pre-governance-docs-20260822` tại baseline `v3.2.2`.
- Historical Git tag trước config migration:
  `backup/pre-config-layout-migration-20260822-184537` tại `5e79f633`.

Các tag `backup/...` trên là lịch sử và không bị xóa. Sau ADR-0004, snapshot
công việc mới chỉ nằm trong thư mục `.local-backups/` bị Git ignore để không can
thiệp `git describe --tags` của Moonraker và không dùng GitHub làm kho backup.

Đây là backup code. Backup dữ liệu printer vẫn phải làm riêng trước mỗi thay đổi
trên máy.
