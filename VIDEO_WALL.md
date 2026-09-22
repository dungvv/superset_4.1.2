# Video Wall - Tích hợp vào Superset

Tính năng Video Wall đã được tích hợp trực tiếp vào Superset, cho phép hiển thị nhiều charts theo dạng lưới với khả năng tự động xoay vòng.

## Truy cập

```
http://your-superset-url/superset/video-wall/
```

## Các cách cấu hình

### Cách 1: Dùng file config JSON

Tạo file `video_wall_config.json` trong thư mục gốc Superset:

```json
{
  "supersetUrl": "http://localhost:8088",
  "rotationInterval": 30,
  "charts": [
    {
      "id": 10,
      "title": "KPI Doanh thu",
      "url": "/explore/?slice_id=10&standalone=true"
    },
    {
      "id": 11,
      "title": "Tỷ lệ chuyển đổi",
      "url": "/explore/?slice_id=11&standalone=true"
    }
  ]
}
```

Cấu hình đường dẫn trong `superset_config.py`:

```python
VIDEO_WALL_CONFIG_PATH = "/path/to/video_wall_config.json"
```

### Cách 2: Dùng Dashboard ID

Truy cập với dashboard ID để tự động lấy tất cả charts từ dashboard:

```
http://your-superset-url/superset/video-wall/123/
```

Trong đó `123` là ID của dashboard.

### Cách 3: Dùng URL params

Chỉ định danh sách chart IDs qua URL:

```
http://your-superset-url/superset/video-wall/?charts=10,11,12,13
```

## Tính năng

- **4 chế độ layout**: 1×1, 2×2, 3×3, 4×3
- **Tự động xoay vòng**: Khi số charts nhiều hơn số ô hiển thị
- **Thời gian xoay**: Cấu hình qua `rotationInterval` (mặc định 30 giây)
- **Title tùy chỉnh**: Hiển thị tên chart phía trên
- **Responsive**: Tự động điều chỉnh trên màn hình nhỏ

## Điều khiển

- **Layout selector**: Chọn chế độ hiển thị ở góc trên bên phải
- **Rotation toggle**: Bật/tắt tự động xoay
- **Info display**: Hiển thị thông tin charts đang xem

## Cấu hình qua biến môi trường

```bash
# Đường dẫn file config
export VIDEO_WALL_CONFIG_PATH="/app/config/video_wall.json"
```

## Lưu ý

- Video wall yêu cầu đăng nhập Superset
- Charts được hiển thị ở chế độ `standalone=true` (ẩn navigation)
- Nếu dùng cross-origin iframe, cần cấu hình `SESSION_COOKIE_SAMESITE = "None"` và `SESSION_COOKIE_SECURE = True`

## Tạo file config tự động

Dùng script `generate_config.py` trong thư mục `video-wall/`:

```bash
cd video-wall
python generate_config.py \
  --url http://localhost:8088 \
  --username admin \
  --password admin \
  --slices 10,11,12,13
```

Script sẽ tự động lấy thông tin charts và tạo file `config.json`.
