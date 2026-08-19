# Cài client export báo cáo trên máy Ubuntu không có internet

Client là `scripts/export_dashboard_word.py`: mở dashboard bằng Playwright, bấm
`Download > Download as Word`, rồi convert docx sang PDF bằng LibreOffice.

Máy đích: **Ubuntu x86_64, Python >= 3.10** (playwright 1.62.0 yêu cầu 3.10+).

Có hai phần phải mang sang, tải riêng bằng hai cách khác nhau:

| Phần | Cách lấy |
|---|---|
| Wheel Python | `pip download` trên máy có mạng |
| Chromium (~170MB) | **Không** nằm trong wheel, tải riêng |
| LibreOffice + font | `apt-get download` trên máy Ubuntu có mạng |

---

## Phần 1 — Wheel Python

Chạy trên máy **có internet**. Quan trọng: phải là Linux x86_64 wheel, không
phải wheel của máy đang tải, nên các cờ `--platform`/`--python-version` là bắt
buộc. `--only-binary=:all:` để pip không tải source rồi build sai kiến trúc.

```bash
mkdir -p offline/wheels
pip download \
  --dest offline/wheels \
  --requirement requirements/client.txt \
  --platform manylinux2014_x86_64 \
  --python-version 310 \
  --only-binary=:all:
```

Nếu máy đích dùng Python 3.11 thì đổi `--python-version 311`. Wheel `cp310`
không cài được trên 3.11 (`greenlet` và `charset-normalizer` có binary).

Kiểm tra đã đúng platform:

```bash
ls offline/wheels | grep -E "greenlet|charset"
# phải thấy ...manylinux..., KHÔNG phải ...macosx... hay ...win_amd64...
```

## Phần 2 — Chromium cho Playwright

`pip install playwright` chỉ cài thư viện Python; Chromium do
`playwright install` tải từ CDN, nên máy offline không tự lấy được.

**Cách A — lấy từ docker image đã có (không cần internet)**

`superser_dungvv.tar.gz` đã chứa sẵn Chromium build 1234 bản Linux, đúng bản mà
playwright 1.62.0 cần:

```bash
# tìm layer chứa ms-playwright
tar -xzOf superser_dungvv.tar.gz \
  blobs/sha256/702424c8fe0d31a4836f4f20ac3d357d32240332175524926656dbfb286f33f8 \
  | tar -xf - -C offline/ ms-playwright
```

**Cách B — tải từ CDN trên máy Linux có mạng**

```bash
pip install playwright==1.62.0
PLAYWRIGHT_BROWSERS_PATH=$PWD/offline/ms-playwright \
  playwright install chromium
```

Không dùng máy macOS cho cách B — nó tải Chromium bản mac, chạy trên Ubuntu sẽ
lỗi `Executable doesn't exist`.

## Phần 3 — LibreOffice + font

Bỏ qua phần này nếu chạy `--no-pdf` (chỉ xuất Word).

Chạy trên **máy Ubuntu có mạng, cùng phiên bản Ubuntu với máy đích** — `.deb`
phụ thuộc phiên bản. Font là cần thiết: thiếu thì chữ tiếng Việt/Lào thành ô
vuông trong PDF (lý do `Dockerfile.dungvv` cài chúng).

```bash
mkdir -p offline/deb && cd offline/deb
apt-get download $(apt-cache depends --recurse --no-recommends --no-suggests \
  --no-conflicts --no-breaks --no-replaces --no-enhances \
  libreoffice-writer fonts-dejavu fonts-liberation fonts-noto-core \
  | grep "^\w" | sort -u)
```

---

## Mang sang máy đích

```bash
tar czf offline-client.tar.gz offline/ requirements/client.txt scripts/
# copy offline-client.tar.gz sang máy Ubuntu đích
```

## Cài trên máy đích

```bash
tar xzf offline-client.tar.gz && cd offline-client

# 1. LibreOffice + font (bỏ qua nếu dùng --no-pdf)
sudo dpkg -i offline/deb/*.deb || sudo apt-get -f install --no-download

# 2. Wheel Python, --no-index để pip không thử ra internet
python3 -m venv venv
./venv/bin/pip install --no-index --find-links offline/wheels \
  -r requirements/client.txt

# 3. Chromium: đặt ngoài /root. Nếu nằm trong /root (mode 0700) thì user chạy
#    cron không đọc được, Playwright tưởng chưa cài và tự đi tải lại.
sudo mv offline/ms-playwright /opt/ms-playwright
sudo chmod -R a+rX /opt/ms-playwright
```

## Kiểm tra

```bash
export PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

./venv/bin/python -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(); print('chromium ok', b.version); b.close()
"
soffice --version
./venv/bin/python scripts/export_dashboard_word.py --self-check
```

Cả bốn lệnh phải chạy được trước khi đặt cron.

## Chạy

`PLAYWRIGHT_BROWSERS_PATH` phải có trong môi trường, kể cả khi chạy bằng cron —
cron không đọc `.bashrc`, nên đặt trong env file.

```bash
# /etc/superset/report.env   (chmod 600)
SUPERSET_URL=https://superset.example.com
SUPERSET_USERNAME=report_bot
SUPERSET_PASSWORD=...
DASHBOARD_ID=1
REPORT_OUTPUT_DIR=/var/lib/superset/reports
PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
REPORT_PYTHON=/opt/superset/venv/bin/python
REPORT_SCRIPT=export_dashboard_word.py
```

```bash
# crontab -e — 8h50 hàng ngày, báo cáo ngày N-1
50 8 * * * /opt/superset/scripts/run_dashboard_report.sh --grain day
```

`--grain day` lấy ngày gần nhất đã kết thúc (hôm qua), nên 8h50 là an toàn.

## Lỗi thường gặp

| Triệu chứng | Nguyên nhân |
|---|---|
| `Executable doesn't exist at .../chrome` | `PLAYWRIGHT_BROWSERS_PATH` chưa set, hoặc tải Chromium bản macOS |
| `is not a supported wheel on this platform` | Sai `--python-version` hoặc `--platform` lúc `pip download` |
| Chữ Việt/Lào thành ô vuông trong PDF | Thiếu font ở Phần 3 |
| `soffice` treo, không trả file | `HOME` không ghi được — đặt `HOME` sang thư mục của user chạy cron |
| Cron không chạy nhưng gõ tay thì được | Thiếu env trong `report.env`, hoặc thiếu `flock` |
| Bấm menu không thấy `Download as Word` | Superset đang hiển thị tiếng khác — sửa nhãn ở `export_dashboard_word.py:92` |
