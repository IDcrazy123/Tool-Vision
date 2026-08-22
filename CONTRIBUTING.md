# Đóng góp cho ToolVision

Cảm ơn bạn muốn cải thiện ToolVision. Đây là phần mềm có thể điều khiển chuyển
động, heater và probe của máy in; thay đổi nhỏ trong code có thể có tác động vật
lý. Vì vậy mọi đóng góp phải ưu tiên bằng chứng và rollback.

## Bắt đầu

1. Đọc [`AGENTS.md`](AGENTS.md), [`docs/README.md`](docs/README.md) và
   [`docs/CODE_CONVENTIONS.md`](docs/CODE_CONVENTIONS.md).
2. Kiểm tra [`docs/RISK_REGISTER.md`](docs/RISK_REGISTER.md) và issue hiện có.
3. Với thay đổi có motion/heater/camera/schema/installer, tạo change plan từ
   [`docs/templates/CHANGE_PLAN.md`](docs/templates/CHANGE_PLAN.md).
4. Tạo branch riêng; không sửa trực tiếp `main`.
5. Viết test tái hiện trước khi sửa lỗi nếu có thể.

## Yêu cầu PR

PR phải nêu:

- vấn đề và behavior trước/sau;
- Risk ID hoặc lý do không liên quan risk register;
- ảnh hưởng đến motion, heater, toolchange, data, API và deployment;
- test đã chạy và môi trường;
- migration/backup/rollback;
- tài liệu đã cập nhật;
- HIL evidence nếu thay đổi hành vi vật lý.

Không gửi threshold computer vision mới chỉ dựa trên một ảnh/một máy. Hãy kèm
corpus hoặc dữ liệu replay có quyền sử dụng rõ.

## Kiểm tra tối thiểu

```bash
python -m unittest discover -s tests -v
python -m compileall -q klippy server tests
bash -n install.sh
bash -n uninstall.sh
git diff --check
```

Xem đầy đủ tại [`docs/TESTING.md`](docs/TESTING.md).

## Style và tương thích

- Tuân thủ hợp đồng chi tiết tại
  [`docs/CODE_CONVENTIONS.md`](docs/CODE_CONVENTIONS.md).
- Giữ code đọc được trên minimum Python đã công bố trong compatibility matrix.
- Không tự động áp toàn bộ autofix nếu có thể phá tương thích Klipper/Python cũ.
- Chú thích lý do cho invariant safety, dấu offset và recovery khó hiểu.
- Không nuốt exception ở đường recovery mà không ghi lại lỗi.
- Không đưa credential, IP riêng, config máy hoặc ảnh không được phép vào Git.

## Tài liệu và quyết định

Thay đổi invariant kiến trúc cần ADR. Thay schema/path cần migration và cập nhật
`DATA_AND_STORAGE.md`. Thay workflow người dùng cần cập nhật README/runbook.

## License

Repository đang có risk mở R-012 về license. Cho đến khi chủ sở hữu công bố
license và Contributor policy, hãy xác nhận quyền đối với code/ảnh/dataset bạn
đóng góp và không sao chép code không tương thích từ project tham chiếu.
