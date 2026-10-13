# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

import logging
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Optional

from superset.commands.report.exceptions import ReportSchedulePdfFailedError

logger = logging.getLogger(__name__)
try:
    from PIL import Image, ImageDraw, ImageFont
except ModuleNotFoundError:
    logger.info("No PIL installation found")

# Layout of the header, designed for a page 1600 px wide and scaled to the
# real page width: white band with the logo on the left and the title lines
# centered on the page.
DESIGN_WIDTH = 1600
HEADER_HEIGHT = 110
LOGO_HEIGHT = 64
HEADER_MARGIN = 50
TITLE_SIZE = 30
# same size as the chart titles of a 1600 px dashboard (theme typography.sizes.l)
SUBTITLE_SIZE = 16
# space between the baseline of a line and the capitals of the next one
TITLE_GAP = 12
TITLE_COLOR = (0, 0, 0)
# the date line under the title is grey (theme grayscale.base)
SUBTITLE_COLOR = (102, 102, 102)
# page number band at the very bottom: height and text size of the 1600 px design
FOOTER_HEIGHT = 52
FOOTER_TEXT_SIZE = 18
FOOTER_TEXT_COLOR = (102, 102, 102)
# share of the header height the logo takes when it sits on a header image
LOGO_HEADER_RATIO = 0.7
LOGO_MAX_WIDTH_RATIO = 0.4
# the logo starts with an icon (a quarter of its width), then the wordmark
# ("money"): the title lines up with the top of the wordmark, not of the icon
LOGO_ICON_WIDTH_RATIO = 0.28

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
)


@dataclass
class PdfDecorations:
    """Images and text added to every page of a report PDF."""

    header: Optional["Image.Image"] = None
    footer: Optional["Image.Image"] = None
    logo: Optional["Image.Image"] = None
    logo_position: str = "left"  # left | center | right
    title_lines: list[str] = field(default_factory=list)
    # font of the title and the date line (semi-bold), and of the page number
    # (regular)
    font_path: Optional[str] = None
    regular_font_path: Optional[str] = None
    # e.g. "Trang {page}" or "Trang {page}/{pages}"; None for no page number
    page_number_format: Optional[str] = None
    page_number_position: str = "center"  # left | center | right


def _load_image(path: Optional[str], what: str) -> Optional["Image.Image"]:
    if not path:
        return None
    try:
        with Image.open(path) as img:
            return img.convert("RGBA")
    except Exception as ex:  # pylint: disable=broad-except
        logger.warning("PDF %s image %s could not be loaded: %s", what, path, ex)
        return None


def get_pdf_decorations(
    config: dict[str, Any], title_lines: Optional[list[str]] = None
) -> Optional[PdfDecorations]:
    """
    Header / footer / logo set in superset_config.py
    (ALERT_REPORTS_PDF_HEADER_IMAGE, ALERT_REPORTS_PDF_FOOTER_IMAGE,
    ALERT_REPORTS_PDF_LOGO, ALERT_REPORTS_PDF_LOGO_POSITION,
    ALERT_REPORTS_PDF_FONT, ALERT_REPORTS_PDF_FONT_REGULAR) plus the title lines of this report, drawn only when
    ALERT_REPORTS_PDF_SHOW_TITLE is on, and the page number footer when
    ALERT_REPORTS_PDF_PAGE_NUMBER is on (ALERT_REPORTS_PDF_PAGE_FORMAT).
    None when there is nothing to add (or no image could be read).
    """
    decorations = PdfDecorations(
        header=_load_image(config.get("ALERT_REPORTS_PDF_HEADER_IMAGE"), "header"),
        footer=_load_image(config.get("ALERT_REPORTS_PDF_FOOTER_IMAGE"), "footer"),
        logo=_load_image(config.get("ALERT_REPORTS_PDF_LOGO"), "logo"),
        logo_position=config.get("ALERT_REPORTS_PDF_LOGO_POSITION") or "left",
        title_lines=(
            [line for line in title_lines or [] if line]
            if config.get("ALERT_REPORTS_PDF_SHOW_TITLE")
            else []
        ),
        font_path=config.get("ALERT_REPORTS_PDF_FONT"),
        regular_font_path=config.get("ALERT_REPORTS_PDF_FONT_REGULAR"),
        page_number_format=(
            config.get("ALERT_REPORTS_PDF_PAGE_FORMAT") or "Trang {page}"
            if config.get("ALERT_REPORTS_PDF_PAGE_NUMBER")
            else None
        ),
        page_number_position=(
            config.get("ALERT_REPORTS_PDF_PAGE_POSITION") or "center"
        ),
    )
    if not (
        decorations.header
        or decorations.footer
        or decorations.logo
        or decorations.title_lines
        or decorations.page_number_format
    ):
        return None
    return decorations


def _fit(img: "Image.Image", width: int = 0, height: int = 0) -> "Image.Image":
    """Resize keeping the aspect ratio to the given width or height."""
    if width:
        height = max(1, round(img.height * width / img.width))
    else:
        width = max(1, round(img.width * height / img.height))
    return img.resize((max(1, width), height), Image.LANCZOS)


def _load_font(font_path: Optional[str], size: int) -> "ImageFont.FreeTypeFont":
    for path in (font_path, *FONT_CANDIDATES):
        if not path:
            continue
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    logger.warning(
        "No font found for the PDF title, set ALERT_REPORTS_PDF_FONT to a TrueType "
        "font that has the characters of the title (Vietnamese, ...)"
    )
    return ImageFont.load_default(size)


def _logo_text_top(logo: "Image.Image") -> int:
    """
    Row where the wordmark of the logo starts (the part right of the icon),
    which is lower than the top of the icon.
    """
    flat = Image.new("RGBA", logo.size, (255, 255, 255, 255))
    flat.alpha_composite(logo)
    rgb = flat.convert("RGB")
    pixels = rgb.load()
    first_column = min(logo.width - 1, int(logo.width * LOGO_ICON_WIDTH_RATIO))
    for y in range(logo.height):
        if any(min(pixels[x, y]) < 200 for x in range(first_column, logo.width)):
            return y
    return 0


def _draw_title(
    canvas: "Image.Image",
    decorations: PdfDecorations,
    scale: float,
    band_height: int,
    max_width: int,
    align_top: Optional[float] = None,
) -> None:
    """
    Title lines, centered on the page. The capitals of the title start at
    align_top (the top of the logo's wordmark) or, without a logo, the title is
    centered in the band; the following lines come right under it.
    """
    draw = ImageDraw.Draw(canvas)
    sizes = [round(TITLE_SIZE * scale), round(SUBTITLE_SIZE * scale)]
    fonts = []
    for index, line in enumerate(decorations.title_lines):
        size = sizes[min(index, len(sizes) - 1)]
        # title and date: semi-bold like the chart titles (only the colour
        # differs); the page number uses the regular font
        font_path = decorations.font_path
        font = _load_font(font_path, size)
        # a long title shrinks until it fits between the logo and the margin
        while draw.textlength(line, font=font) > max_width and size > 8:
            size -= 1
            font = _load_font(font_path, size)
        fonts.append(font)
    gap = round(TITLE_GAP * scale)
    # (top, baseline) of the capitals of each line, from where the text is drawn
    caps = [(font.getbbox("H")[1], font.getbbox("H")[3]) for font in fonts]
    if align_top is not None:
        y = align_top - caps[0][0]
    else:
        y = band_height / 2 - (caps[0][0] + caps[0][1]) / 2
    baseline = y + caps[0][1]
    for index, (line, font) in enumerate(zip(decorations.title_lines, fonts)):
        if index:
            y = baseline + gap - caps[index][0]
            baseline = y + caps[index][1]
        x = (canvas.width - draw.textlength(line, font=font)) / 2
        color = TITLE_COLOR if index == 0 else SUBTITLE_COLOR
        draw.text((x, y), line, font=font, fill=color)


def _draw_page_number(
    canvas: "Image.Image",
    decorations: PdfDecorations,
    scale: float,
    top: int,
    page_number: int,
    total_pages: int,
) -> None:
    """Page number in the white band that starts at `top`: left, centre or right
    (same margin as the logo), centred vertically."""
    text = (decorations.page_number_format or "").replace(
        "{pages}", str(total_pages)
    ).replace("{page}", str(page_number))
    font = _load_font(
        decorations.regular_font_path or decorations.font_path,
        round(FOOTER_TEXT_SIZE * scale),
    )
    draw = ImageDraw.Draw(canvas)
    left, text_top, right, bottom = font.getbbox(text)
    band = round(FOOTER_HEIGHT * scale)
    margin = round(HEADER_MARGIN * scale)
    text_width = right - left
    x = {
        "left": margin,
        "right": canvas.width - margin - text_width,
    }.get(decorations.page_number_position, (canvas.width - text_width) / 2) - left
    y = top + (band - (bottom - text_top)) / 2 - text_top
    draw.text((x, y), text, font=font, fill=FOOTER_TEXT_COLOR)


def decorate_page(
    page: "Image.Image",
    decorations: PdfDecorations,
    page_number: int = 1,
    total_pages: int = 1,
) -> "Image.Image":
    """
    Page with the header on top and the footer at the bottom, both scaled to
    the page width. The logo and the title lines are drawn on the header (on a
    white band of its own when there is no header image). The page number
    (page_number of total_pages) goes in a white band under everything else.
    """
    width = page.width
    scale = width / DESIGN_WIDTH
    header = _fit(decorations.header, width=width) if decorations.header else None
    footer = _fit(decorations.footer, width=width) if decorations.footer else None

    has_band = bool(header or decorations.logo or decorations.title_lines)
    top_height = (
        header.height
        if header
        else (round(HEADER_HEIGHT * scale) if has_band else 0)
    )

    logo = None
    if decorations.logo:
        logo = _fit(
            decorations.logo,
            height=round(top_height * LOGO_HEADER_RATIO)
            if header
            else round(LOGO_HEIGHT * scale),
        )
        if logo.width > width * LOGO_MAX_WIDTH_RATIO:
            logo = _fit(logo, width=round(width * LOGO_MAX_WIDTH_RATIO))

    number_height = (
        round(FOOTER_HEIGHT * scale) if decorations.page_number_format else 0
    )
    bottom_height = (footer.height if footer else 0) + number_height
    canvas = Image.new("RGB", (width, top_height + page.height + bottom_height), "white")
    if header:
        canvas.paste(header, (0, 0), header)
    margin = round(HEADER_MARGIN * scale)
    logo_right = 0
    align_top: Optional[float] = None
    if logo:
        x = {
            "center": (width - logo.width) // 2,
            "right": width - logo.width - margin,
        }.get(decorations.logo_position, margin)
        logo_top = (top_height - logo.height) // 2
        canvas.paste(logo, (x, logo_top), logo)
        logo_right = x + logo.width if decorations.logo_position == "left" else 0
        align_top = logo_top + _logo_text_top(logo)
    if decorations.title_lines:
        # centered on the page, so it must stay clear of a logo on the left
        free = width / 2 - logo_right - margin * 0.6
        _draw_title(
            canvas,
            decorations,
            scale,
            top_height,
            round(2 * free) if logo_right else round(width * 0.9),
            align_top,
        )
    canvas.paste(page, (0, top_height))
    if footer:
        canvas.paste(footer, (0, top_height + page.height), footer)
    if number_height:
        _draw_page_number(
            canvas,
            decorations,
            scale,
            top_height + page.height + bottom_height - number_height,
            page_number,
            total_pages,
        )
    return canvas


def build_pdf_from_screenshots(
    snapshots: list[bytes],
    decorations: Optional[PdfDecorations] = None,
    pixel_density: float = 1,
) -> bytes:
    """
    One page per screenshot. pixel_density is the one the screenshots were taken
    with (WEBDRIVER_WINDOW["pixel_density"]): the pages keep their size in the
    PDF and get that many times more pixels, so the report stays sharp.
    """
    images = []

    for number, snap in enumerate(snapshots, start=1):
        img = Image.open(BytesIO(snap))
        if img.mode == "RGBA":
            img = img.convert("RGB")
        if decorations:
            img = decorate_page(
                img.convert("RGB"), decorations, number, len(snapshots)
            )
        images.append(img)
    logger.info("building pdf")
    try:
        new_pdf = BytesIO()
        # JPEG quality 95 without chroma subsampling: the Pillow defaults (75,
        # 4:2:0) smear small text and colored edges
        images[0].save(
            new_pdf,
            "PDF",
            save_all=True,
            append_images=images[1:],
            resolution=72 * pixel_density,
            quality=95,
            subsampling=0,
        )
        new_pdf.seek(0)
    except Exception as ex:
        raise ReportSchedulePdfFailedError(
            f"Failed converting screenshots to pdf {str(ex)}"
        ) from ex

    return new_pdf.read()
