# KPI Line Chart — Day Detail (Drill-down)

Tài liệu thiết kế tính năng: **click điểm trên KPI line** → mở bảng chi tiết theo ngày, và màn hình **cấu hình SQL detail** (chỉ áp dụng cho plugin KPI line).

> Trạng thái: thiết kế / ý tưởng — chưa triển khai code.

---

## 1. Mục tiêu

| Hành vi | Kết quả |
|---|---|
| **Hold / hover** điểm trên line | Giữ như hiện tại: tooltip (thời gian, số liệu) |
| **Click** điểm trên line | Mở bảng chi tiết **ngày đó** |
| Dòng không đạt KPI | **Bôi đỏ** (theo cột cờ trong SQL) |
| Nội dung bảng | Do **SQL custom** (tách khỏi SQL/dataset của line chart) |
| Cấu hình SQL / cột cờ | Màn hình riêng, vào từ menu `⋯` trên chart |

Chỉ dành cho **KPI line chart** (`viz_type` của plugin custom), không áp dụng chart loại khác.

---

## 2. Tách hai lớp dữ liệu

```
┌──────────────────────────────┐
│  KPI Line (đã có)            │
│  Dataset / SQL xu hướng      │
│  → series theo ngày, % KPI   │
└──────────────┬───────────────┘
               │ click ngày D
               ▼
┌──────────────────────────────┐
│  Day Detail Table (mới)      │
│  SQL riêng + cột cờ fail     │
│  → list bản ghi trong ngày D │
└──────────────────────────────┘
```

- Line và bảng **không** dùng chung một kết quả cache “full data rồi filter client”.
- Click ngày D → gọi **query mới** (hoặc cache đúng query ngày D + filter), với tham số ngày (và filter dashboard nếu cần).

---

## 3. Luồng người dùng trên dashboard

```
1. User mở dashboard, xem KPI line
2. Hold điểm  → tooltip (ngày, tỉ lệ, …)           [giữ nguyên]
3. Click điểm → lấy category/ngày D từ ECharts
4. Mở modal / drawer “Chi tiết {ngày D}”
5. Backend chạy SQL detail với click_date = D
   (+ native filter dashboard nếu SQL hỗ trợ)
6. Render table; dòng có cờ fail → nền đỏ
7. User đóng modal → về chart
```

### Phác thảo UI

```
┌─ Dashboard ─────────────────────────────────────┐
│  [KPI Line]   • • • ● • •                       │
│                   ↑ click 12/09                 │
│  ┌─ Chi tiết 12/09/2026 ────────────────── [x] │
│  │ ID  │ Giờ  │ Phút │ … │ is_kpi_fail         │
│  │ 101 │ 09:01│ 2.1  │ … │ 0                   │
│  │ 205 │ 09:15│ 12   │ … │ 1   ← tô đỏ         │
│  │ 309 │ 10:02│ 1.0  │ … │ 0                   │
│  └─────────────────────────────────────────────│
└─────────────────────────────────────────────────┘
```

---

## 4. Hợp đồng SQL detail

SQL do người cấu hình **bắt buộc**:

1. **Nhận ngày click** qua Jinja (ví dụ):
   - `{{ click_date }}`, hoặc
   - khoảng `from_dttm` / `to_dttm` thu hẹp đúng ngày D  
   Cần xử lý an toàn khi biến trống (tránh lỗi kiểu Sync columns / `TO_DATE('')`).

2. **Có cột cờ phân loại** đạt / không đạt KPI, ví dụ:
   - `is_kpi_fail` ∈ `{0, 1}`, hoặc
   - `kpi_flag` ∈ `{PASS, FAIL}`

3. Các cột còn lại = nội dung hiển thị trên bảng (ID, thời gian, đơn vị, SLA…).

**Logic “không đạt KPI” nằm trong SQL**, không suy từ % trên line chart. FE chỉ đọc cột cờ để tô đỏ.

Ví dụ tinh thần:

```sql
SELECT
  id,
  create_time,
  approval_time,
  ...,
  CASE WHEN /* điều kiện không đạt KPI */ THEN 1 ELSE 0 END AS is_kpi_fail
FROM ...
WHERE TRUNC(ngay_cot) = TO_DATE('{{ click_date }}', 'YYYY-MM-DD')
  -- + filter_values(...) nếu cần đồng bộ dashboard
```

---

## 5. Filter dashboard

Khi mở bảng chi tiết ngày D, nên kế thừa ngữ cảnh:

- Ngày click = grain chi tiết trong ngày D  
- Native filter khác (trạng thái, kênh…) nếu SQL detail dùng `filter_values(...)` / tương đương  

Line = xu hướng theo ngày; bảng = bản ghi trong một ngày — **cùng filter context**, khác mức chi tiết.

---

## 6. Menu cấu hình (chỉ KPI line)

Trên header chart (dấu **⋯**), cạnh **Edit chart**:

| Mục menu | Đối tượng | Chức năng |
|---|---|---|
| **Edit chart** | Như hiện tại | Explore: metric, time, style line / KPI card |
| **Edit detail table** *(tên gợi ý)* | **Chỉ** KPI line | Màn/modal cấu hình SQL detail + cột cờ |

Gợi ý tên khác:

- Configure drill-down  
- Edit day detail  
- Tiếng Việt: **Chỉnh bảng chi tiết** / **Cấu hình chi tiết theo ngày**

### Điều kiện hiện menu

```
viz_type === '<kpi_line_viz_type>'
VÀ user có quyền edit chart (owner / admin / can_write Chart)
```

Chart Table, Big Number, v.v. **không** có mục này.

### Nội dung màn Edit detail

- Ô SQL (Jinja) cho bảng chi tiết  
- Tên cột cờ (mặc định `is_kpi_fail`)  
- (Tuỳ chọn) limit số dòng, danh sách cột hiển thị, tiêu đề modal  
- Save → ghi vào cấu hình chart  

---

## 7. Lưu cấu hình (đề xuất)

| Cách | Mô tả | Khuyến nghị giai đầu |
|---|---|---|
| **A. Chart params** | SQL + tên cột cờ nằm trong JSON params của slice | ✅ Đơn giản, export chart mang theo |
| **B. Dataset thứ 2** | Trỏ dataset/table riêng | Linh hoạt hơn về sau |
| **C. Bảng metadata riêng** | Quản trị tập trung | Overkill giai 1 |

Nên bắt đầu với **A**.

---

## 8. Quy tắc tô đỏ

| `is_kpi_fail` (hoặc tương đương) | Hiển thị |
|---|---|
| `1` / `FAIL` | Cả dòng đỏ nhạt (hoặc chữ đỏ) |
| `0` / `PASS` | Bình thường |
| Thiếu cột / SQL lỗi | Bảng vẫn cố hiện hoặc báo lỗi; không tô đỏ tùy chọn |

Tooltip hover **không** đổi hành vi; chỉ **click** mở bảng.

---

## 9. Kiến trúc tổng quan

```
┌─────────────────────────────────────┐
│ SliceHeader ⋯                       │
│  - Edit chart      → Explore        │
│  - Edit detail     → Detail setup   │  (chỉ KPI line)
│    table             (SQL + cờ)     │
└─────────────────────────────────────┘

┌─────────────────────────────────────┐
│ KpiLineChart (ECharts)              │
│  hover → tooltip                    │
│  click point → ngày D               │
│       → Detail Modal + fetch SQL    │
└─────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│ API chart/data hoặc endpoint riêng  │
│ params: click_date, filters, SQL    │
│ từ chart params                     │
└─────────────────────────────────────┘
```

---

## 10. Ranh giới / không nhầm với

| Trong phạm vi | Ngoài phạm vi (có thể làm sau) |
|---|---|
| Click điểm → modal bảng SQL custom + tô đỏ | Cross-filter sang chart khác trên dashboard |
| Menu setup chỉ KPI line | Thay thế “View query” / Explore mặc định |
| Logic fail KPI trong SQL detail | Plugin tự suy fail từ series % trên line |
| | Hard-reload / auto-refresh dashboard |

---

## 11. Lộ trình triển khai gợi ý

1. **Spec cứng:** tên cột cờ, format `click_date`, quyền edit  
2. **Menu `⋯` + màn Edit detail** → lưu vào chart params  
3. **ECharts click** → modal table + gọi API  
4. **Tô đỏ** theo cột cờ  
5. **1–2 SQL mẫu IPCC** + validate Jinja (tránh `TO_DATE('')` khi sync/test)  

---

## 12. Tóm tắt một câu

Giữ tooltip khi hold; **click ngày trên KPI line** mở bảng từ **SQL riêng** có cột cờ fail để tô đỏ; cấu hình SQL đó qua mục menu riêng (**Edit detail table**), **chỉ hiện với KPI line chart**.
