from importlib.resources import files
from pathlib import Path
from string import ascii_letters

from PIL import Image, ImageFont

from holoquiz.minecraft_text_ocr import FONT_GLYPHS
from holoquiz.minecraft_text_ocr import GLYPHS
from holoquiz.minecraft_text_ocr import MINECRAFT_FONT_CHARACTERS
from holoquiz.minecraft_text_ocr import _read_glyph
from holoquiz.minecraft_text_ocr import read_minecraft_text


def test_read_minecraft_text_from_real_afk_crop():
    image = Image.open(
        Path(__file__).parent / "fixtures" / "minecraft-you-are-now-afk.png"
    )

    text = read_minecraft_text(image)

    assert text == "You are now AFK"


def test_read_minecraft_text_from_real_result_line():
    image = Image.open(
        Path(__file__).parent
        / "fixtures"
        / "minecraft-nice-day-for-fishing-screen.png"
    ).crop((1010, 550, 1450, 620))

    text = read_minecraft_text(image)

    assert text == "Nice day for fishing"


def test_read_minecraft_text_from_real_cookie_result_crop():
    image = Image.open(
        Path(__file__).parent
        / "fixtures"
        / "minecraft-dont-eat-to-much-cookies.png"
    )

    text = read_minecraft_text(image)

    assert text == "Don't eat to much cookies!"


def test_read_minecraft_text_from_real_where_are_you_crop():
    image = Image.open(
        Path(__file__).parent / "fixtures" / "minecraft-where-are-you.png"
    )

    text = read_minecraft_text(image)

    assert text == "Where are you?"


def test_read_minecraft_text_from_real_case_sensitive_prompt_crop():
    image = Image.open(
        Path(__file__).parent
        / "fixtures"
        / "minecraft-enter-message-case-sensitive.png"
    )

    text = read_minecraft_text(image)

    assert text == "Enter the message you see into chat (case sensitive!)"


def test_read_minecraft_text_handles_scaled_colored_glyph_variants():
    image = Image.open(
        Path(__file__).parent / "fixtures" / "minecraft-i-love-holocraft.png"
    )

    text = read_minecraft_text(image)

    assert text == "I Love Holocraft"


def test_read_minecraft_text_from_blue_lowercase_alphabet():
    image = Image.open(
        Path(__file__).parent / "fixtures" / "minecraft-lowercase-alphabet-blue.png"
    )

    text = read_minecraft_text(image)

    assert text == "abcdefghijklmnopqrstuvwxyz"


def test_read_minecraft_text_from_blue_uppercase_alphabet():
    image = Image.open(
        Path(__file__).parent / "fixtures" / "minecraft-uppercase-alphabet-blue.png"
    )

    text = read_minecraft_text(image)

    assert text == "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def test_read_minecraft_text_from_blue_afk_again_prompt():
    image = Image.open(
        Path(__file__).parent / "fixtures" / "minecraft-afk-again-blue.png"
    )

    text = read_minecraft_text(image)

    assert text == "Afk again?"


def test_read_minecraft_text_from_blue_mixed_font_string():
    image = Image.open(
        Path(__file__).parent / "fixtures" / "minecraft-mixed-font-blue.png"
    )

    text = read_minecraft_text(image)

    assert text == "AnQpSowiQmznApo!?7!NWmw1Po123i"


def test_read_minecraft_text_from_second_blue_mixed_font_string():
    image = Image.open(
        Path(__file__).parent / "fixtures" / "minecraft-mixed-font-blue-2.png"
    )

    text = read_minecraft_text(image)

    assert text == "P9Oak1mNasdpo1i23bNzm1291!?7"


def test_read_minecraft_text_keeps_repeated_uppercase_and_lowercase_shapes():
    image = Image.open(
        Path(__file__).parent / "fixtures" / "minecraft-mixed-font-blue-3.png"
    )

    text = read_minecraft_text(image)

    assert text == "ssggGGlkmankj123poi"


def test_bundled_minecraft_font_loads_supported_characters():
    font_path = files("holoquiz").joinpath("assets", "minecraft_font.ttf")
    font = ImageFont.truetype(str(font_path), 32)

    assert font.getname() == ("Minecraft", "Regular")
    assert all(font.getbbox(character) for character in MINECRAFT_FONT_CHARACTERS)


def test_minecraft_glyph_table_covers_english_alphabet():
    supported_letters = set(GLYPHS.values()) & set(ascii_letters)

    assert supported_letters == set(ascii_letters)


def test_minecraft_font_reference_characters_are_readable():
    image = Image.open(
        Path(__file__).parent / "fixtures" / "minecraft-font-reference.png"
    )

    failures = {}
    for line_relative in (False, True):
        failures.update(
            {
                character: _read_glyph(pattern)
                for character, pattern in _extract_reference_font_patterns(
                    image,
                    line_relative=line_relative,
                ).items()
                if _read_glyph(pattern) != character
            }
        )

    assert set(FONT_GLYPHS.values()) == set(MINECRAFT_FONT_CHARACTERS)
    assert failures == {}


def _extract_reference_font_patterns(image, *, line_relative=False):
    row_tops = [4, 81, 158, 251, 328, 405, 498, 575, 652]
    column_lefts = [3, 74, 145, 216, 287, 358, 429, 500, 571]
    rows = [
        "ABCDEFGHI",
        "JKLMNOPQR",
        "STUVWXYZ",
        "abcdefghi",
        "jklmnopqr",
        "stuvwxyz",
        "012345678",
        "9.,;:$#'!",
        "\"/?%&()@",
    ]

    patterns = {}
    for row_index, characters in enumerate(rows):
        row_crops = []
        row_dark_pixels = []
        for column_index, character in enumerate(characters):
            crop = image.crop(
                (
                    column_lefts[column_index],
                    row_tops[row_index],
                    column_lefts[column_index] + 71,
                    row_tops[row_index] + 77,
                )
            )
            dark_pixels = _find_dark_pixels(crop)
            row_crops.append((character, crop, dark_pixels))
            row_dark_pixels.extend(dark_pixels)

        row_top = min(y for _x, y in row_dark_pixels)
        row_bottom = max(y for _x, y in row_dark_pixels)
        for character, crop, dark_pixels in row_crops:
            patterns[character] = _extract_dark_glyph_pattern(
                crop,
                dark_pixels,
                top=row_top if line_relative else None,
                bottom=row_bottom if line_relative else None,
            )
    return patterns


def _find_dark_pixels(image):
    pixels = image.convert("RGB").load()
    return [
        (x, y)
        for y in range(image.height)
        for x in range(image.width)
        if max(pixels[x, y]) < 90
    ]


def _extract_dark_glyph_pattern(image, dark_pixels, *, top=None, bottom=None):
    pixels = image.convert("RGB").load()
    min_x = min(x for x, _y in dark_pixels)
    max_x = max(x for x, _y in dark_pixels)
    if top is None:
        top = min(y for _x, y in dark_pixels)
    if bottom is None:
        bottom = max(y for _x, y in dark_pixels)
    width = max_x - min_x + 1
    height = bottom - top + 1

    rows = []
    for grid_y in range(8):
        row = ""
        y_start = top + grid_y * height // 8
        y_end = top + (grid_y + 1) * height // 8
        for grid_x in range(8):
            x_start = min_x + grid_x * width // 8
            x_end = min_x + (grid_x + 1) * width // 8
            total = 0
            dark_count = 0
            for y in range(y_start, y_end):
                for x in range(x_start, x_end):
                    total += 1
                    if max(pixels[x, y]) < 90:
                        dark_count += 1
            row += "#" if total and dark_count > total * 0.25 else "."
        rows.append(row)
    return tuple(rows)
