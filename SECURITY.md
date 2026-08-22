# Chính sách bảo mật và safety

ToolVision là phần mềm điều khiển phụ trợ cho máy in 3D. Báo cáo cần xem cả bảo
mật phần mềm lẫn nguy cơ chuyển động/heater/probe không an toàn.

## Phạm vi ưu tiên

- request có thể chặn Klipper hoặc làm MCU timeout;
- chuyển động/probe ngoài envelope hoặc recovery không an toàn;
- heater không cleanup;
- API host bị truy cập trái phép;
- camera URL/credential bị lộ;
- dependency/update/install có thể thực thi code ngoài ý muốn;
- state/result/config bị ghi đè, giả mạo hoặc migration sai;
- detector/transform có thể chấp nhận kết quả sai một cách có hệ thống.

## Cách báo cáo

Ưu tiên GitHub Security Advisory/private vulnerability report của repository nếu
tính năng đó khả dụng. Nếu không có kênh private, mở issue tối thiểu chỉ nêu rằng
cần liên hệ riêng; không đăng exploit, credential, địa chỉ máy hoặc config nhạy
cảm công khai.

Báo cáo nên có:

- version/commit;
- điều kiện tái hiện và mức tác động;
- log đã redaction;
- liệu có motion/heat/data loss hay không;
- workaround an toàn nếu đã biết.

## Triển khai an toàn

- Giữ host service bind `127.0.0.1` như mặc định.
- Không port-forward API 8085 trực tiếp ra LAN/Internet; API hiện không auth.
- Không đặt credential camera trong issue/log/support bundle.
- Chỉ update từ remote/branch đã kiểm tra và repository sạch.
- Chạy dependency audit và review changelog trước release.
- Máy phải idle khi install, update HIL hoặc restore.

## Phiên bản được xử lý

Cho đến khi có support matrix chính thức, chỉ latest release/main được kiểm tra
best-effort. Đây không phải cam kết rằng mọi phiên bản cũ còn nhận bản vá. Khi
báo lỗi, luôn thử xác định liệu lỗi còn tồn tại ở latest release trên môi trường
an toàn.

## Sự cố đang diễn ra

Nếu heater/chuyển động đang không an toàn, ưu tiên emergency procedure của máy,
không ưu tiên thu log. Sau khi máy an toàn, giữ nguyên log/state/result và dùng
[`docs/templates/INCIDENT_REPORT.md`](docs/templates/INCIDENT_REPORT.md).
