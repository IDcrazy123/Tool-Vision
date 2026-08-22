# Quy trình phát hành

## Loại release

- Patch: sửa lỗi tương thích/hành vi không đổi schema/API chủ đích.
- Minor: capability mới tương thích ngược, có thể thêm schema/API có migration.
- Major: thay invariant, workflow, API/schema không tương thích hoặc chính sách
  áp offset.

Version hiện còn lặp ở nhiều file (R-016); trước khi hợp nhất version source,
release phải kiểm tra tất cả nơi khai báo.

## Trước khi merge release

- [ ] Scope/issue/Risk ID rõ.
- [ ] Backup tag trước thay đổi đã push.
- [ ] Change plan và rollback được review.
- [ ] Code review đã kiểm tra motion/heat/data/deployment impact.
- [ ] Changelog, README và tài liệu liên quan cập nhật.
- [ ] Schema/API/config migration có test.
- [ ] Dependency change có audit và compatibility evidence.
- [ ] Không có file generated/secret/camera credential trong Git.

## Quality gate

- [ ] 100% test hiện có pass.
- [ ] Python compile pass.
- [ ] Coverage critical path không giảm không giải thích.
- [ ] Safety lint được phân loại; không thêm silent broad catch.
- [ ] Bash syntax/config contracts pass.
- [ ] Runtime requirement audit pass hoặc exception được phê duyệt.
- [ ] Corpus replay pass nếu đổi camera/detector/transform.
- [ ] Simulator/integration pass nếu đổi Klippy/toolchanger.
- [ ] HIL pass nếu đổi motion/probe/heater/transport.
- [ ] Fresh install/N-1 upgrade/rollback pass nếu đổi deployment/schema.

Lưu kết quả theo [`templates/RELEASE_EVIDENCE.md`](templates/RELEASE_EVIDENCE.md).

## Chuẩn bị version

1. Chọn version theo impact, không theo số lượng dòng.
2. Cập nhật version source và contract test.
3. Cập nhật `CHANGELOG.md`, ngày release và known limitations.
4. Xác nhận `git diff --check`, worktree sạch sau commit.
5. Tạo annotated semantic release tag `vX.Y.Z` hoặc prerelease được Moonraker
   hỗ trợ như `vX.Y.Z-rcN`; không di chuyển tag đã push.
6. Chạy `python scripts/release_metadata.py --expected X.Y.Z[-rcN]`; chuỗi
   `git describe` bắt đầu bằng `backup/` là release blocker.
7. Push branch và tag; xác minh remote hash/tag dereference.

Backup công việc mới nằm trong `.local-backups/` bị Git ignore, không phải
branch/tag GitHub. Các backup tag lịch sử được giữ nguyên theo ADR-0004 và không
được xóa để “sửa” UI.

## Canary qua Moonraker

1. Chọn máy pilot idle, backup config/state/result và ghi hardware revisions.
2. Refresh Update Manager; xác nhận đúng remote commit/version.
3. Update riêng `tool-vision`, không “Update all”.
4. Xác nhận:
   - repository clean, correct branch/hash, behind 0;
   - host `/api/v2/health` đúng version;
   - Klipper `ready`, object `tool_vision.version` đúng version;
   - state/stations còn hợp lệ;
   - service/Moonraker log không có warning mới.
5. Chạy smoke/HIL gate phù hợp impact.
6. Theo dõi trước khi mở rộng rollout.

## Rollout

- Không rollout rộng nếu canary chỉ “service starts” nhưng thay đổi liên quan
  phép đo chưa chạy HIL.
- Mỗi hardware class mới bắt đầu như canary riêng.
- Release note nêu rõ cần setup lại hay không, data migration, backup và cách
  nhận biết thành công.
- Nếu phát hiện P0/P1 mới, dừng rollout, publish advisory/revert và giữ evidence.

## Rollback gate

Trước release phải biết:

- code sẽ quay về version nào;
- state/schema mới có đọc được ở version cũ không;
- backup matching nằm ở đâu và checksum đã kiểm tra chưa;
- Mainsail rollback hay revert release là đường chính;
- smoke test nào chứng minh rollback hoàn tất.

Không dùng hard reset tùy tiện trên printer Git runtime. Xem
[`BACKUP_RESTORE.md`](BACKUP_RESTORE.md).

## Sau release

- [ ] GitHub branch/tag đúng hash.
- [ ] Moonraker remote/current version đúng trên canary.
- [ ] Release evidence được commit/link.
- [ ] Risk register cập nhật trạng thái và bằng chứng.
- [ ] Compatibility matrix cập nhật đúng mức Observed/Tested/Supported.
- [ ] Incident/known limitation được ghi, không chỉ nằm trong chat/log.
- [ ] Backup trước release được giữ đến khi restore drill pass.
