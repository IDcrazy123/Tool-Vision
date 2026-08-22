# Detector và camera transform — nguồn, quyết định, giới hạn

Tài liệu này mô tả logic đang thử nghiệm trong `v3.3.0-rc1`. Nó phân biệt rõ
phần kế thừa từ dự án tham chiếu, phần được kiểm chứng bằng tài liệu thư viện và
phần còn cần corpus ảnh thật/HIL. Đây không phải tuyên bố rằng một bộ ngưỡng phù
hợp với mọi camera hoặc mọi nozzle.

## Nguồn đã khóa khi review

- kTAMV commit
  [`72421f2`](https://github.com/TypQxQ/kTAMV/tree/72421f2d54da0de8701c4f84449c6e6b7d060301):
  mười điểm bán kính 0,5 mm, yêu cầu ít nhất 75% điểm, nhiều chiến lược
  preprocessing, ba vị trí liên tiếp và lọc mm/pixel ngoại lai.
- Axiscope commit
  [`9a1a9ef`](https://github.com/nic335/Axiscope/tree/9a1a9efe3cfa6dc1e816acaaea87f8ac513282f6):
  nguồn đối chiếu Z/switch và workflow nhiệt; Axiscope không có detector camera
  XY để ToolVision sao chép.
- [OpenCV thresholding](https://docs.opencv.org/4.13.0/d7/d4d/tutorial_py_thresholding.html),
  [contour retrieval/shape](https://docs.opencv.org/4.12.0/d3/dc0/group__imgproc__shape.html)
  và [contour properties](https://docs.opencv.org/4.12.0/d1/d32/tutorial_py_contour_properties.html):
  định nghĩa adaptive/Otsu threshold, contour, area, perimeter, convex hull.
- [OpenCV SimpleBlobDetector](https://docs.opencv.org/4.12.0/d8/da7/structcv_1_1SimpleBlobDetector_1_1Params.html):
  nguồn kiểm tra ý nghĩa threshold/circularity/convexity; tài liệu không đưa ra
  một giá trị “đúng cho mọi nozzle”.
- [OpenCV image I/O environment](https://docs.opencv.org/4.12.0/d6/dea/tutorial_env_reference.html)
  và [VideoCapture properties](https://docs.opencv.org/4.12.0/d4/d15/group__videoio__flags__base.html):
  giới hạn pixel giải mã và timeout open/read của backend FFmpeg/GStreamer.
- [NumPy `lstsq`](https://numpy.org/doc/stable/reference/generated/numpy.linalg.lstsq.html)
  và [condition number](https://numpy.org/doc/stable/reference/generated/numpy.linalg.cond.html):
  bình phương tối thiểu chỉ tối ưu residual; rank/condition và validation độc
  lập vẫn phải do ứng dụng kiểm tra.
- [OpenCV camera calibration](https://docs.opencv.org/4.10.0/d4/d94/tutorial_camera_calibration.html)
  và [planar homography](https://docs.opencv.org/4.5.2/d9/dab/tutorial_homography.html):
  pixel không tự mang đơn vị mm và ánh xạ mặt phẳng phải được hiệu chuẩn từ các
  cặp điểm. ToolVision dùng mô hình tuyến tính cục bộ quanh tâm camera; chưa
  tuyên bố mô hình này đủ cho trường nhìn lớn trước HIL.

## Điều kế thừa và điều không sao chép

| Nguồn | Giữ lại | Không sao chép nguyên trạng |
|---|---|---|
| kTAMV | vòng 10 điểm ±0,5 mm; ba frame ổn định; ≥8/10 điểm; học từ nozzle thật | 640×480 cố định; chọn im lặng blob gần tâm khi có nhiều blob; bộ threshold cố định; chỉ dùng training fit để kết luận |
| Axiscope | switch vật lý, trigger delta theo reference, workflow 150 °C từ ví dụ chính thức | tọa độ fixture khai báo trước; Axiscope không cung cấp camera detector XY |
| OpenCV/NumPy | primitive và ý nghĩa toán học | không coi default/tham số ví dụ của thư viện là tiêu chuẩn nozzle |

## Pipeline phát hiện

1. Giữ độ phân giải gốc và áp flip/rotation từ Moonraker.
2. Trong setup, thử adaptive dark/light, Otsu dark/light và edge trên một burst
   năm frame.
3. Xếp hạng candidate theo độ ổn định, gần tâm, hình học và tương phản; học
   strategy/kích thước/hình học từ nozzle người dùng đã đặt gần tâm.
4. Runtime yêu cầu ba frame liên tiếp ổn định ở đúng độ phân giải đã học.
5. Nếu hai vật thể ở hai vị trí khác nhau cùng khớp profile, dừng với lỗi thay
   vì chọn vật gần tâm. Các contour đồng tâm của cùng một cạnh được gộp vì
   `RETR_LIST` có thể trả cả contour trong và ngoài.
6. Sharpness chỉ được báo để chẩn đoán. Nó không phải ngưỡng pass/fail tuyệt đối.

Các giới hạn area/radius/shape rất rộng trong bước tạo candidate là guardrail
nội bộ nhằm tránh contour suy biến và tải không giới hạn; chúng không phải
thông số chuẩn từ OpenCV. Chúng vẫn cần được kiểm chứng/chỉnh bằng corpus ảnh
thật theo R-006, nhưng không được chuyển thành hàng loạt knob trong `.cfg`.

## Transform và tiêu chí chấp nhận

Mỗi điểm lưu `pixel_delta`, `machine_delta` và độ phân tán `stability_px` đo
trong chính burst đó. Mô hình dùng quy ước hàng:

```text
machine_delta = pixel_delta dot matrix
```

Fit chỉ được chấp nhận khi:

- có 8–64 sample hữu hạn và chuyển động ảnh span đủ hai trục;
- ít nhất 75% điểm nhất quán, ma trận full-rank và condition ≤100;
- training RMS và leave-one-out RMS cùng nằm trong giới hạn nội bộ;
- độ nhiễu pixel quan sát được, với floor lượng tử 0,5 pixel, khi ánh xạ qua
  spectral norm của ma trận không vượt `CENTER_TOLERANCE` 0,015 mm.

Các số 75% và vòng mười điểm bám theo kTAMV. `CENTER_TOLERANCE` là yêu cầu chính
xác của ToolVision, không phải tuyên bố accuracy camera; nếu phần cứng không
chứng minh được yêu cầu này thì setup fail-closed. Khi center, chỉ chấp nhận nếu
`distance_mm + estimated_uncertainty_mm` nằm trong tolerance.

Condition 100, residual allowance và các guardrail hình học là giới hạn kỹ
thuật nội bộ bảo thủ, không phải “giá trị chuẩn OpenCV”. Chúng được giữ để không
mở rộng acceptance khi chưa có dữ liệu và phải được đánh giá lại từ corpus/HIL;
người dùng không được yêu cầu tinh chỉnh chúng trong `.cfg`.

Transform schema 2 lưu training RMS, leave-one-out RMS, condition, pixel noise,
gain mm/pixel và bất định ước lượng. Transform schema 1 không có đủ evidence nên
không được dùng tiếp; người dùng phải backup state rồi chạy lại
`TV_SETUP_CAMERA` sau khi lên `v3.3.0-rc1`.

## Freshness, tài nguyên và concurrency

- Sau mỗi correction move, observation mới phải dịch chuyển nhiều hơn noise
  quan sát/floor 0,5 pixel nếu vẫn chưa vào tolerance. Frame cache/frozen giống
  hệt sẽ dừng chuyển động với lỗi rõ.
- HTTP image bị giới hạn cả byte nén và 16 megapixel giải nén. 16 MP là budget
  tài nguyên (xấp xỉ 48 MiB cho BGR), không phải ngưỡng chất lượng ảnh.
- RTSP/RTMP/RTP/UDP/TCP/SRT truyền timeout vào lúc `VideoCapture.open`; OpenCV
  chỉ bảo đảm thuộc tính này với backend được tài liệu nêu. Local device backend
  vẫn là phần chưa đóng của R-010.
- `configuring` khóa start/detect/transform mutation cho đến khi camera mới đã
  capture và validate xong. Nếu configure fail, runtime cũ được giữ nguyên.
- Klippy nạp lại profile/transform đã lưu trước mỗi calibration XY vì host
  service không lưu state và có thể vừa được Moonraker restart.

## Bằng chứng hiện có và gate còn thiếu

`v3.3.0-rc1` có unit/component regression cho distractor, frame sai, scale cực
đoan, outlier, uncertainty, frozen frame, ảnh quá lớn, timeout-open contract và
configure race. Đây chỉ là bằng chứng synthetic/fake.

Chưa được phép gọi bản này “ổn định đa phần cứng” cho đến khi hoàn tất:

- corpus ảnh thật có nhãn blur/glare/nozzle bẩn/distractor/no-nozzle/frozen;
- replay so với baseline và ghi false accept/false reject;
- HIL lặp lại trên máy pilot sau backup, gồm service restart giữa setup và
  calibration;
- đối chiếu kết quả XY với chuẩn độc lập hoặc print validation đã định nghĩa.

Chi tiết gate nằm trong [`TESTING.md`](TESTING.md), trạng thái trong
[`RISK_REGISTER.md`](RISK_REGISTER.md).
