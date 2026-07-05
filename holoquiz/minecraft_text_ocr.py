from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from string import ascii_lowercase, ascii_uppercase
from typing import Any


GlyphPattern = tuple[str, ...]
FUZZY_GLYPH_MAX_DISTANCE = 5
FUZZY_GLYPH_MIN_MARGIN = 2
MINECRAFT_FONT_CHARACTERS = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789.,;:$#'!"
    "\"/?%&()@"
)
X_HEIGHT_LOWERCASE = set("acegmnopqrsuvwxyz")


FONT_GLYPHS: dict[GlyphPattern, str] = {
    ('..#####.', '##....##', '########', '########', '##....##', '##....##', '##....##', '##....##'): 'A',
    ('#######.', '##.....#', '########', '########', '##.....#', '##.....#', '##.....#', '#######.'): 'B',
    ('..#####.', '##....##', '##.....#', '##......', '##......', '##......', '##.....#', '..#####.'): 'C',
    ('#######.', '##....##', '##....##', '##....##', '##....##', '##....##', '##....##', '#######.'): 'D',
    ('########', '##......', '#####...', '#####...', '##......', '##......', '##......', '########'): 'E',
    ('########', '##......', '#####...', '#####...', '##......', '##......', '##......', '##......'): 'F',
    ('..######', '##......', '##...###', '##...###', '##.....#', '##.....#', '##.....#', '..#####.'): 'G',
    ('##....##', '##....##', '########', '########', '##....##', '##....##', '##....##', '##....##'): 'H',
    ('########', '...###..', '...###..', '...###..', '...###..', '...###..', '...###..', '########'): 'I',
    ('......##', '......##', '......##', '......##', '......##', '#.....##', '##....##', '..#####.'): 'J',
    ('##.....#', '##...##.', '#####...', '####.#..', '##...###', '##.....#', '##.....#', '##.....#'): 'K',
    ('##......', '##......', '##......', '##......', '##......', '##......', '##......', '########'): 'L',
    ('##....##', '###..###', '##.##.##', '##..#.##', '##....##', '##....##', '##....##', '##....##'): 'M',
    ('##....##', '###...##', '##.##.##', '##..####', '##...###', '##....##', '##....##', '##....##'): 'N',
    ('..#####.', '##.....#', '##.....#', '##.....#', '##.....#', '##.....#', '##....##', '..#####.'): 'O',
    ('#######.', '##....##', '#######.', '######..', '##......', '##......', '##......', '##......'): 'P',
    ('..#####.', '##....##', '##....##', '##....##', '##....##', '##...###', '##...##.', '..###.##'): 'Q',
    ('#######.', '##.....#', '#######.', '########', '##.....#', '##.....#', '##.....#', '##.....#'): 'R',
    ('..######', '##......', '#######.', '..######', '......##', '......##', '##....##', '..#####.'): 'S',
    ('########', '...##...', '...##...', '...##...', '...##...', '...##...', '...##...', '...##...'): 'T',
    ('##.....#', '##.....#', '##.....#', '##.....#', '##.....#', '##.....#', '##.....#', '..#####.'): 'U',
    ('##....##', '##....##', '##....##', '##....##', '###..###', '..#..##.', '..#..##.', '...##...'): 'V',
    ('##....##', '##....##', '##....##', '##....##', '##..#.##', '##.##.##', '###..###', '##....##'): 'W',
    ('##.....#', '.###.##.', '..####..', '..####..', '###..###', '##.....#', '##.....#', '##.....#'): 'X',
    ('##....##', '..#..##.', '..####..', '...##...', '...##...', '...##...', '...##...', '...##...'): 'Y',
    ('########', '......##', '.....###', '...###..', '..###...', '.##.....', '##......', '########'): 'Z',
    ('..#####.', '..#####.', '......##', '..######', '.#######', '##....##', '########', '..######'): 'a',
    ('##......', '##......', '##.###..', '########', '####...#', '##.....#', '##.....#', '#######.'): 'b',
    ('..#####.', '..#####.', '##.....#', '##......', '##......', '##.....#', '########', '..#####.'): 'c',
    ('......##', '......##', '..###.##', '########', '##...###', '##....##', '##....##', '..######'): 'd',
    ('..#####.', '.######.', '##....##', '########', '########', '##......', '########', '..######'): 'e',
    ('....####', '..##....', '########', '########', '..##....', '..##....', '..##....', '..##....'): 'f',
    ('..######', '##....##', '##....##', '##....##', '..######', '..######', '......##', '#######.'): 'g',
    ('##......', '##......', '##.###..', '########', '###...##', '##....##', '##....##', '##....##'): 'h',
    ('.#######', '........', '.#######', '.#######', '.#######', '.#######', '.#######', '.#######'): 'i',
    ('......##', '........', '......##', '......##', '......##', '##....##', '##....##', '..#####.'): 'j',
    ('##......', '##......', '##....##', '##..####', '######..', '#####...', '##..###.', '##....##'): 'k',
    ('####....', '####....', '####....', '####....', '####....', '####....', '####....', '....####'): 'l',
    ('###..##.', '####.##.', '##.##.##', '##.##.##', '##.##.##', '##....##', '##....##', '##....##'): 'm',
    ('#######.', '#######.', '##....##', '##....##', '##....##', '##....##', '##....##', '##....##'): 'n',
    ('..#####.', '.######.', '##.....#', '##.....#', '##.....#', '##.....#', '##....##', '..#####.'): 'o',
    ('##.####.', '########', '###...##', '##....##', '#######.', '#######.', '##......', '##......'): 'p',
    ('..###.##', '########', '##...###', '##....##', '.#######', '..######', '......##', '......##'): 'q',
    ('##.####.', '##.####.', '####...#', '###....#', '##......', '##......', '##......', '##......'): 'r',
    ('..######', '.#######', '##......', '..#####.', '..#####.', '......##', '#######.', '#######.'): 's',
    ('...###..', '########', '########', '...###..', '...###..', '...###..', '...###..', '.....###'): 't',
    ('##....##', '##....##', '##....##', '##....##', '##....##', '##....##', '..######', '..######'): 'u',
    ('##....##', '##....##', '##....##', '##....##', '##....##', '..#..##.', '...##...', '...##...'): 'v',
    ('##....##', '##....##', '##....##', '##.##.##', '##.##.##', '##.##.##', '.#######', '..######'): 'w',
    ('##.....#', '##....##', '..##.##.', '...##...', '...##...', '..##.##.', '##.....#', '##.....#'): 'x',
    ('##....##', '##....##', '##....##', '##....##', '..######', '..######', '......##', '#######.'): 'y',
    ('########', '########', '.....##.', '...##...', '...##...', '..#.....', '########', '########'): 'z',
    ('..#####.', '##....##', '##...###', '##.#####', '#####.##', '###...##', '##....##', '..#####.'): '0',
    ('...##...', '..###...', '...##...', '...##...', '...##...', '...##...', '...##...', '########'): '1',
    ('..#####.', '##....##', '......##', '...#####', '..####..', '###.....', '##......', '########'): '2',
    ('..#####.', '##.....#', '.......#', '...#####', '...#####', '#......#', '##....##', '..#####.'): '3',
    ('.....###', '...##.##', '..##..##', '###...##', '########', '########', '......##', '......##'): '4',
    ('########', '##......', '#######.', '########', '.......#', '#......#', '##....##', '..#####.'): '5',
    ('...####.', '..#.....', '##......', '######..', '########', '##....##', '##....##', '..#####.'): '6',
    ('########', '##....##', '......##', '.....###', '....###.', '...##...', '...##...', '...##...'): '7',
    ('..#####.', '##.....#', '##.....#', '########', '########', '##.....#', '##....##', '..#####.'): '8',
    ('..#####.', '##....##', '##....##', '########', '..######', '......##', '.....##.', '..###...'): '9',
    ('.######.', '.#######', '.#######', '.#######', '.#######', '.#######', '.#######', '.#######'): '.',
    ('.###.###', '.###.###', '.###.###', '.###.###', '.###.###', '.###.###', '.###.###', '.###.###'): ',',
    ('.#######', '.#######', '.#######', '........', '.#######', '.#######', '.#######', '.#######'): ';',
    ('.#######', '.#######', '.#######', '........', '........', '.#######', '.#######', '.#######'): ':',
    ('...##...', '..######', '########', '#######.', '..######', '......##', '#######.', '...##...'): '$',
    ('..#..##.', '..#..##.', '########', '########', '########', '########', '..#..##.', '..#..##.'): '#',
    ('.#######', '.#######', '.#######', '.#######', '.#######', '.#######', '.#######', '.#######'): "'",
    ('.#######', '.#######', '.#######', '.#######', '.#######', '.#######', '........', '.#######'): '!',
    ('###..###', '###..###', '###..###', '###..###', '###..###', '###..###', '###..###', '###..###'): '"',
    ('.......#', '.....##.', '.....##.', '...###..', '..###...', '..##....', '..##....', '##......'): '/',
    ('..#####.', '##....##', '#......#', '.....###', '.....##.', '...##...', '........', '...##...'): '?',
    ('##....##', '##...##.', '#....##.', '...###..', '..###...', '..#.....', '..#...##', '##....##'): '%',
    ('...##...', '..##.#..', '..####..', '..###..#', '########', '##.###..', '##...#..', '..###.##'): '&',
    ('....####', '..###...', '####....', '##......', '##......', '###.....', '..###...', '....####'): '(',
    ('####....', '....##..', '....####', '......##', '......##', '......##', '....##..', '####....'): ')',
    ('.######.', '##....##', '##.##..#', '##.##..#', '##.#####', '##.#####', '##......', '.#######'): '@',
}

FONT_GLYPHS.update({
    ('........', '........', '..#####.', '......##', '..######', '##....##', '..######', '........'): 'a',
    ('##......', '##......', '##.####.', '####...#', '##.....#', '##.....#', '#######.', '........'): 'b',
    ('........', '........', '..#####.', '##.....#', '##......', '##.....#', '..#####.', '........'): 'c',
    ('......##', '......##', '..###.##', '##...###', '##....##', '##....##', '..######', '........'): 'd',
    ('........', '........', '..#####.', '##....##', '########', '##......', '..######', '........'): 'e',
    ('....####', '..##....', '########', '..##....', '..##....', '..##....', '..##....', '........'): 'f',
    ('........', '........', '..######', '##....##', '##....##', '..######', '......##', '#######.'): 'g',
    ('##......', '##......', '##.####.', '###...##', '##....##', '##....##', '##....##', '........'): 'h',
    ('.#######', '........', '.#######', '.#######', '.#######', '.#######', '.#######', '........'): 'i',
    ('##......', '##......', '##....##', '##..###.', '#####...', '##..###.', '##....##', '........'): 'k',
    ('####....', '####....', '####....', '####....', '####....', '####....', '....####', '........'): 'l',
    ('........', '........', '###..##.', '##.##.##', '##.##.##', '##....##', '##....##', '........'): 'm',
    ('........', '........', '#######.', '##....##', '##....##', '##....##', '##....##', '........'): 'n',
    ('........', '........', '..#####.', '##....##', '##.....#', '##.....#', '..#####.', '........'): 'o',
    ('........', '........', '##.####.', '####..##', '##....##', '#######.', '##......', '##......'): 'p',
    ('........', '........', '..###.##', '##...###', '##....##', '.#######', '......##', '......##'): 'q',
    ('........', '........', '##.####.', '####..##', '##......', '##......', '##......', '........'): 'r',
    ('........', '........', '..######', '##......', '..#####.', '......##', '#######.', '........'): 's',
    ('...###..', '########', '...###..', '...###..', '...###..', '...###..', '.....###', '........'): 't',
    ('........', '........', '##....##', '##....##', '##....##', '##....##', '..######', '........'): 'u',
    ('........', '........', '##....##', '##....##', '##....##', '..#..##.', '...##...', '........'): 'v',
    ('........', '........', '##....##', '##....##', '##.##.##', '##.##.##', '..######', '........'): 'w',
    ('........', '........', '##.....#', '..##.##.', '...##...', '..##.##.', '##.....#', '........'): 'x',
    ('........', '........', '##....##', '##....##', '##....##', '..######', '......##', '#######.'): 'y',
    ('........', '........', '########', '.....##.', '...##...', '..#.....', '########', '........'): 'z',
    ('..#####.', '##....##', '##....##', '..######', '......##', '.....##.', '..###...', '........'): '9',
    ('........', '........', '........', '........', '........', '.#######', '.#######', '........'): '.',
    ('........', '........', '........', '........', '........', '.###.###', '.###.###', '.###.###'): ',',
    ('........', '.#######', '.#######', '........', '........', '.#######', '.#######', '.#######'): ';',
    ('........', '.#######', '.#######', '........', '........', '.#######', '.#######', '........'): ':',
    ('...##...', '..######', '##......', '..#####.', '.......#', '#######.', '...##...', '........'): '$',
    ('..#..##.', '..#..##.', '########', '..##.##.', '########', '..#..##.', '..#..##.', '........'): '#',
    ('.#######', '.#######', '........', '........', '........', '........', '........', '........'): "'",
    ('.#######', '.#######', '.#######', '.#######', '.#######', '........', '.#######', '........'): '!',
    ('###..###', '###..###', '###...##', '........', '........', '........', '........', '........'): '"',
})


GLYPHS: dict[GlyphPattern, str] = {
    (
        "####.",
        "#...#",
        "#...#",
        "#...#",
        "#...#",
        "#...#",
        "####.",
    ): "D",
    (
        "#...#",
        "##..#",
        "#.#.#",
        "#..##",
        "#...#",
        "#...#",
        "#...#",
    ): "N",
    (
        "#...#",
        ".#.#.",
        "..#..",
        "..#..",
        "..#..",
        "..#..",
        "..#..",
    ): "Y",
    (
        ".....",
        ".....",
        ".###.",
        "#...#",
        "#...#",
        "#...#",
        ".###.",
    ): "o",
    (
        ".....",
        ".....",
        "#...#",
        "#...#",
        "#...#",
        "#...#",
        ".####",
    ): "u",
    (
        "#...#",
        "#...#",
        "#...#",
        "#...#",
        "#...#",
        "#####",
        ".####",
    ): "u",
    (
        ".....",
        ".....",
        ".###.",
        "....#",
        ".####",
        "#...#",
        ".####",
    ): "a",
    (
        ".....",
        ".....",
        "#.##.",
        "##..#",
        "#....",
        "#....",
        "#....",
    ): "r",
    (
        ".....",
        ".....",
        ".###.",
        "#...#",
        "#####",
        "#....",
        ".####",
    ): "e",
    (
        ".....",
        ".....",
        "####.",
        "#...#",
        "#...#",
        "#...#",
        "#...#",
    ): "n",
    (
        ".....",
        ".....",
        "#...#",
        "#...#",
        "#.#.#",
        "#.#.#",
        ".####",
    ): "w",
    (
        "#...#",
        "#...#",
        "#...#",
        "#.#.#",
        "#.#.#",
        "#####",
        ".####",
    ): "w",
    (
        "#...#",
        "#...#",
        "#...#",
        "#...#",
        "#.#.#",
        "##.##",
        "#...#",
    ): "W",
    (
        ".###.",
        "#...#",
        "#####",
        "#...#",
        "#...#",
        "#...#",
        "#...#",
    ): "A",
    (
        "#####",
        "#....",
        "###..",
        "#....",
        "#....",
        "#....",
        "#....",
    ): "F",
    (
        "#...#",
        "#..#.",
        "###..",
        "#..#.",
        "#...#",
        "#...#",
        "#...#",
    ): "K",
    (
        ".####",
        ".....",
        ".####",
        ".####",
        ".####",
        ".####",
        ".####",
    ): "i",
    (
        ".####",
        ".####",
        ".####",
        ".####",
        ".####",
        ".####",
        ".####",
    ): "'",
    (
        "..##.",
        "..##.",
        "#####",
        "..##.",
        "..##.",
        "..##.",
        "...##",
    ): "t",
    (
        ".###.",
        "#####",
        "#...#",
        "#....",
        "#...#",
        "#####",
        ".###.",
    ): "c",
    (
        ".###.",
        "#####",
        "#...#",
        "#####",
        "#####",
        "#####",
        ".####",
    ): "e",
    (
        "....#",
        "....#",
        ".##.#",
        "#..##",
        "#...#",
        "#...#",
        ".####",
    ): "d",
    (
        ".###.",
        ".####",
        "....#",
        ".####",
        "#####",
        "#####",
        ".####",
    ): "a",
    (
        "#...#",
        "#...#",
        "#...#",
        "#####",
        ".####",
        "....#",
        "####.",
    ): "y",
    (
        "..###",
        ".##..",
        "#####",
        ".##..",
        ".##..",
        ".##..",
        ".##..",
    ): "f",
    (
        ".###.",
        "#####",
        "#...#",
        "#...#",
        "#...#",
        "#####",
        ".###.",
    ): "o",
    (
        "#.##.",
        "#####",
        "##..#",
        "#....",
        "#....",
        "#....",
        "#....",
    ): "r",
    (
        ".####",
        "#####",
        "#....",
        ".###.",
        ".####",
        "#####",
        "####.",
    ): "s",
    (
        "#....",
        "#....",
        "#.##.",
        "##..#",
        "#...#",
        "#...#",
        "#...#",
    ): "h",
    (
        "####.",
        "#####",
        "#...#",
        "#...#",
        "#...#",
        "#...#",
        "#...#",
    ): "n",
    (
        "##.#.",
        "#####",
        "#.#.#",
        "#.#.#",
        "#.#.#",
        "#...#",
        "#...#",
    ): "m",
    (
        "##...",
        "##...",
        "##..#",
        "####.",
        "###..",
        "####.",
        "##..#",
    ): "k",
    (
        ".####",
        "#####",
        "#...#",
        "#####",
        ".####",
        "....#",
        "####.",
    ): "g",
    (
        ".####",
        ".####",
        ".####",
        ".####",
        ".####",
        ".....",
        ".####",
    ): "!",
    (
        "####.",
        "#...#",
        "#...#",
        "####.",
        "#...#",
        "#...#",
        "####.",
    ): "B",
    (
        ".####",
        "#....",
        "#....",
        "#....",
        "#....",
        "#....",
        ".####",
    ): "C",
    (
        "#####",
        "#....",
        "#....",
        "####.",
        "#....",
        "#....",
        "#####",
    ): "E",
    (
        ".####",
        "#....",
        "#....",
        "#.###",
        "#...#",
        "#...#",
        ".####",
    ): "G",
    (
        "#...#",
        "#...#",
        "#...#",
        "#####",
        "#...#",
        "#...#",
        "#...#",
    ): "H",
    (
        "#####",
        "..#..",
        "..#..",
        "..#..",
        "..#..",
        "..#..",
        "#####",
    ): "I",
    (
        "..###",
        "...#.",
        "...#.",
        "...#.",
        "#..#.",
        "#..#.",
        ".##..",
    ): "J",
    (
        "#....",
        "#....",
        "#....",
        "#....",
        "#....",
        "#....",
        "#####",
    ): "L",
    (
        "#...#",
        "##.##",
        "#.#.#",
        "#...#",
        "#...#",
        "#...#",
        "#...#",
    ): "M",
    (
        ".###.",
        "#...#",
        "#...#",
        "#...#",
        "#...#",
        "#...#",
        ".###.",
    ): "O",
    (
        "####.",
        "#...#",
        "#...#",
        "####.",
        "#....",
        "#....",
        "#....",
    ): "P",
    (
        ".###.",
        "#...#",
        "#...#",
        "#...#",
        "#.#.#",
        "#..#.",
        ".##.#",
    ): "Q",
    (
        "####.",
        "#...#",
        "#...#",
        "####.",
        "#.#..",
        "#..#.",
        "#...#",
    ): "R",
    (
        ".####",
        "#....",
        "#....",
        ".###.",
        "....#",
        "....#",
        "####.",
    ): "S",
    (
        "#####",
        "..#..",
        "..#..",
        "..#..",
        "..#..",
        "..#..",
        "..#..",
    ): "T",
    (
        "#...#",
        "#...#",
        "#...#",
        "#...#",
        "#...#",
        "#...#",
        ".###.",
    ): "U",
    (
        "#...#",
        "#...#",
        "#...#",
        "#...#",
        "#...#",
        ".#.#.",
        "..#..",
    ): "V",
    (
        "#...#",
        "#...#",
        ".#.#.",
        "..#..",
        ".#.#.",
        "#...#",
        "#...#",
    ): "X",
    (
        "#####",
        "....#",
        "...#.",
        "..#..",
        ".#...",
        "#....",
        "#####",
    ): "Z",
    (
        "#....",
        "#....",
        "#.##.",
        "##..#",
        "#...#",
        "#...#",
        "####.",
    ): "b",
    (
        "..##.",
        ".....",
        "..##.",
        "..##.",
        "..##.",
        "#.##.",
        ".##..",
    ): "j",
    (
        ".##..",
        "..#..",
        "..#..",
        "..#..",
        "..#..",
        "..#..",
        ".###.",
    ): "l",
    (
        ".....",
        ".....",
        "####.",
        "#...#",
        "#...#",
        "####.",
        "#....",
    ): "p",
    (
        ".####",
        "#...#",
        "#...#",
        ".####",
        "....#",
        "....#",
        "....#",
    ): "q",
    (
        "#...#",
        "#...#",
        "#...#",
        "#...#",
        ".#.#.",
        ".#.#.",
        "..#..",
    ): "v",
    (
        ".....",
        ".....",
        "#...#",
        ".#.#.",
        "..#..",
        ".#.#.",
        "#...#",
    ): "x",
    (
        "#####",
        "...#.",
        "..#..",
        ".#...",
        "#....",
        "#....",
        "#####",
    ): "z",
    (
        "#####",
        "##...",
        "###..",
        "##...",
        "#....",
        "#....",
        "#####",
    ): "E",
    (
        ".###.",
        ".###.",
        "#####",
        ".###.",
        ".###.",
        ".###.",
        "...##",
    ): "t",
    (
        "#....",
        "#....",
        "#.##.",
        "##..#",
        "##..#",
        "#...#",
        "#...#",
    ): "h",
    (
        "#....",
        "#....",
        "#.##.",
        "###.#",
        "##..#",
        "#...#",
        "#...#",
    ): "h",
    (
        ".###.",
        "####.",
        "#...#",
        "#####",
        "#####",
        "####.",
        ".####",
    ): "e",
    (
        "##.#.",
        "#####",
        "#.#.#",
        "#.#.#",
        "#...#",
        "#...#",
        "#...#",
    ): "m",
    (
        ".####",
        "#####",
        "#....",
        ".###.",
        "..###",
        "#####",
        "####.",
    ): "s",
    (
        ".####",
        "#####",
        "#....",
        ".###.",
        ".####",
        ".####",
        "####.",
    ): "s",
    (
        ".####",
        ".####",
        "#....",
        ".###.",
        ".####",
        ".####",
        "####.",
    ): "s",
    (
        ".####",
        ".####",
        "#....",
        ".###.",
        ".####",
        "#####",
        "####.",
    ): "s",
    (
        ".###.",
        ".###.",
        "....#",
        ".####",
        "#####",
        "#####",
        ".####",
    ): "a",
    (
        "#...#",
        "#...#",
        "#...#",
        "#...#",
        "##.##",
        ".###.",
        "..#..",
    ): "v",
    (
        "...##",
        "..##.",
        "##...",
        "##...",
        "##...",
        "..##.",
        "...##",
    ): "(",
    (
        "##...",
        "..##.",
        "...##",
        "...##",
        "...##",
        "..##.",
        "##...",
    ): ")",
}


@dataclass(frozen=True)
class ColumnGroup:
    start: int
    end: int


def read_minecraft_text(image: Any) -> str:
    rgb_image = image.convert("RGB")
    mask_pixels = _find_text_pixels(rgb_image)
    if not mask_pixels:
        return ""

    groups = _column_groups(mask_pixels)
    if not groups:
        return ""

    line_top = min(y for _x, y in mask_pixels)
    line_bottom = max(y for _x, y in mask_pixels)
    letter_gap = _normal_letter_gap(groups)

    text_parts: list[str] = []
    previous_group: ColumnGroup | None = None
    for group in groups:
        if previous_group is not None:
            gap = group.start - previous_group.end - 1
            if gap >= letter_gap * 2.5:
                text_parts.append(" ")

        allowed_characters = _allowed_characters_for_group(
            mask_pixels,
            group,
            line_top,
            line_bottom,
        )
        font_pattern = _glyph_pattern(
            rgb_image,
            mask_pixels,
            group,
            grid_width=8,
            grid_height=8,
            top=line_top,
            bottom=line_bottom,
        )
        glyph = _read_glyph_from_table(
            font_pattern,
            FONT_GLYPHS,
            allowed_characters=allowed_characters,
        )
        if glyph is None:
            glyph = _fuzzy_glyph_match(
                font_pattern,
                FONT_GLYPHS,
                allowed_characters=allowed_characters,
                max_distance=1,
            )
        legacy_pattern = _glyph_pattern(rgb_image, mask_pixels, group)
        legacy_glyph = _read_legacy_glyph(
            legacy_pattern,
            allowed_characters=allowed_characters,
        )
        if glyph is None:
            glyph = _fuzzy_glyph_match(
                font_pattern,
                FONT_GLYPHS,
                allowed_characters=allowed_characters,
                max_distance=2,
                min_margin=8,
            )
        if glyph is None and legacy_glyph not in {"?", "A", "F", "H"}:
            glyph = legacy_glyph
        if glyph is None:
            glyph = _read_glyph_by_template(
                mask_pixels,
                group,
                line_top,
                line_bottom,
                allowed_characters=allowed_characters,
            )
        if (
            glyph is not None
            and legacy_glyph in ascii_uppercase
            and glyph in ascii_lowercase
        ):
            glyph = legacy_glyph
        if glyph is None and legacy_glyph == "?":
            glyph = _fuzzy_glyph_match(
                font_pattern,
                FONT_GLYPHS,
                allowed_characters=allowed_characters,
                max_distance=6,
                min_margin=2,
                accept_close_ties=True,
            )
        if glyph is None:
            glyph = legacy_glyph
        text_parts.append(glyph)
        previous_group = group

    return "".join(text_parts).strip()


def _read_glyph(pattern: GlyphPattern) -> str:
    return _read_glyph_from_table(pattern, FONT_GLYPHS) or _read_legacy_glyph(pattern)


def _read_legacy_glyph(
    pattern: GlyphPattern,
    *,
    allowed_characters: set[str] | None = None,
) -> str:
    exact_match = GLYPHS.get(pattern)
    if exact_match is not None and _character_allowed(exact_match, allowed_characters):
        return exact_match

    fuzzy_match = _fuzzy_glyph_match(
        pattern,
        GLYPHS,
        allowed_characters=allowed_characters,
    )
    if fuzzy_match is not None:
        return fuzzy_match

    structural_match = _structural_glyph_match(pattern)
    if structural_match is not None and _character_allowed(
        structural_match,
        allowed_characters,
    ):
        return structural_match

    return "?"


def _read_glyph_from_table(
    pattern: GlyphPattern,
    glyphs: dict[GlyphPattern, str],
    *,
    allowed_characters: set[str] | None = None,
) -> str | None:
    exact_match = glyphs.get(pattern)
    if exact_match is None:
        return None
    if not _character_allowed(exact_match, allowed_characters):
        return None
    return exact_match


def _allowed_characters_for_group(
    mask_pixels: set[tuple[int, int]],
    group: ColumnGroup,
    line_top: int,
    line_bottom: int,
) -> set[str] | None:
    group_pixels = [
        (x, y)
        for x, y in mask_pixels
        if group.start <= x <= group.end
    ]
    group_top = min(y for _x, y in group_pixels)
    group_bottom = max(y for _x, y in group_pixels)
    line_height = line_bottom - line_top + 1
    top_offset = group_top - line_top
    bottom_offset = line_bottom - group_bottom

    punctuation = set(MINECRAFT_FONT_CHARACTERS) - set(ascii_lowercase) - set(
        ascii_uppercase
    )
    if top_offset <= max(2, line_height * 0.1) and bottom_offset <= max(
        2,
        line_height * 0.1,
    ):
        return set(MINECRAFT_FONT_CHARACTERS) - X_HEIGHT_LOWERCASE
    if top_offset >= max(3, line_height * 0.18):
        return set(ascii_lowercase) | punctuation
    return None


def _character_allowed(
    character: str,
    allowed_characters: set[str] | None,
) -> bool:
    return allowed_characters is None or character in allowed_characters


def _read_glyph_by_template(
    mask_pixels: set[tuple[int, int]],
    group: ColumnGroup,
    line_top: int,
    line_bottom: int,
    *,
    allowed_characters: set[str] | None = None,
) -> str | None:
    font_pattern = _glyph_pattern_from_bitmap(mask_pixels, group, line_top, line_bottom)
    structural_match = _structural_font_glyph_match(font_pattern)
    if structural_match is not None and _character_allowed(
        structural_match,
        allowed_characters,
    ):
        return structural_match

    actual_pixels = _glyph_bitmap(mask_pixels, group, line_top, line_bottom)
    width = group.end - group.start + 1
    height = line_bottom - line_top + 1

    ttf_match = _read_glyph_by_ttf_template(
        actual_pixels,
        width=width,
        height=height,
        allowed_characters=allowed_characters,
    )
    if ttf_match is not None:
        return ttf_match

    ranked_matches = sorted(
        (
            _bitmap_distance(
                actual_pixels,
                _pattern_bitmap(pattern, width=width, height=height),
            ),
            glyph,
        )
        for pattern, glyph in FONT_GLYPHS.items()
        if _character_allowed(glyph, allowed_characters)
    )
    if not ranked_matches:
        return None

    best_distance, best_glyph = ranked_matches[0]
    second_distance = ranked_matches[1][0] if len(ranked_matches) > 1 else 1.0
    if best_distance > 0.26:
        return None
    if second_distance - best_distance < 0.01:
        return None
    return best_glyph


def _glyph_pattern_from_bitmap(
    mask_pixels: set[tuple[int, int]],
    group: ColumnGroup,
    top: int,
    bottom: int,
) -> GlyphPattern:
    width = group.end - group.start + 1
    height = bottom - top + 1
    rows: list[str] = []
    for grid_y in range(8):
        row = ""
        y_start = top + grid_y * height // 8
        y_end = top + (grid_y + 1) * height // 8
        for grid_x in range(8):
            x_start = group.start + grid_x * width // 8
            x_end = group.start + (grid_x + 1) * width // 8
            total = 0
            text_count = 0
            for y in range(y_start, y_end):
                for x in range(x_start, x_end):
                    total += 1
                    if (x, y) in mask_pixels:
                        text_count += 1
            row += "#" if total and text_count > total * 0.25 else "."
        rows.append(row)
    return tuple(rows)


def _structural_font_glyph_match(pattern: GlyphPattern) -> str | None:
    row_counts = _row_counts(pattern)
    if _looks_like_uppercase_g(pattern):
        return "G"
    if _looks_like_digit_two(pattern):
        return "2"
    if _looks_like_digit_three(pattern):
        return "3"
    if (
        row_counts[0] >= 4
        and row_counts[1] >= 2
        and row_counts[2] >= 1
        and row_counts[3] >= 1
        and row_counts[4] >= 1
        and row_counts[5] == 0
        and row_counts[6] >= 1
        and row_counts[7] == 0
    ):
        return "?"
    return None


def _looks_like_uppercase_g(pattern: GlyphPattern) -> bool:
    row_counts = _row_counts(pattern)
    return (
        row_counts[0] >= 5
        and row_counts[1] >= 2
        and _has_left_pixels(pattern[1])
        and _has_left_pixels(pattern[2])
        and _has_right_pixels(pattern[2])
        and all(_has_left_pixels(row) for row in pattern[3:6])
        and all(_has_right_pixels(row) for row in pattern[3:6])
        and row_counts[6] >= 5
        and row_counts[7] == 0
    )


def _looks_like_digit_two(pattern: GlyphPattern) -> bool:
    row_counts = _row_counts(pattern)
    return (
        row_counts[0] >= 4
        and row_counts[1] >= 3
        and row_counts[2] <= 3
        and _has_right_pixels(pattern[2])
        and row_counts[3] >= 2
        and row_counts[4] <= 3
        and _has_left_pixels(pattern[4])
        and row_counts[5] <= 3
        and _has_left_pixels(pattern[5])
        and row_counts[6] >= 6
    )


def _looks_like_digit_three(pattern: GlyphPattern) -> bool:
    row_counts = _row_counts(pattern)
    return (
        row_counts[0] >= 4
        and row_counts[1] >= 3
        and row_counts[2] <= 3
        and _has_right_pixels(pattern[2])
        and row_counts[3] >= 3
        and row_counts[4] <= 3
        and _has_right_pixels(pattern[4])
        and row_counts[5] >= 3
        and _has_left_pixels(pattern[5])
        and _has_right_pixels(pattern[5])
        and row_counts[6] >= 4
    )


def _has_left_pixels(row: str) -> bool:
    return "#" in row[:3]


def _has_right_pixels(row: str) -> bool:
    return "#" in row[-3:]


def _read_glyph_by_ttf_template(
    actual_pixels: list[list[bool]],
    *,
    width: int,
    height: int,
    allowed_characters: set[str] | None = None,
) -> str | None:
    if (
        allowed_characters is not None
        and allowed_characters & set(ascii_lowercase)
        and not allowed_characters & set(ascii_uppercase)
    ):
        return None

    ranked_matches = sorted(
        (
            _bitmap_distance(actual_pixels, bitmap),
            character,
        )
        for character, bitmap in _ttf_template_bitmaps(width, height)
        if _character_allowed(character, allowed_characters)
    )
    if not ranked_matches:
        return None

    best_distance, best_character = ranked_matches[0]
    second_distance = ranked_matches[1][0] if len(ranked_matches) > 1 else 1.0
    if best_distance > 0.33:
        return None
    if second_distance - best_distance < 0.01:
        return None
    return best_character


@lru_cache(maxsize=256)
def _ttf_template_bitmaps(width: int, height: int) -> tuple[tuple[str, tuple[tuple[bool, ...], ...]], ...]:
    templates: dict[str, tuple[float, tuple[tuple[bool, ...], ...]]] = {}
    for character in MINECRAFT_FONT_CHARACTERS:
        for font_size in (24, 28, 32, 36, 44, 52):
            bitmap = _render_ttf_glyph_bitmap(character, font_size, width, height)
            filled_ratio = _bitmap_filled_ratio(bitmap)
            existing = templates.get(character)
            if existing is None or filled_ratio > existing[0]:
                templates[character] = (filled_ratio, bitmap)
    return tuple((character, bitmap) for character, (_ratio, bitmap) in templates.items())


def _render_ttf_glyph_bitmap(
    character: str,
    font_size: int,
    width: int,
    height: int,
) -> tuple[tuple[bool, ...], ...]:
    from PIL import Image, ImageDraw, ImageFont

    font_path = files("holoquiz").joinpath("assets", "minecraft_font.ttf")
    font = ImageFont.truetype(str(font_path), font_size)
    left, top, right, bottom = font.getbbox(character)
    image = Image.new("L", (max(1, right - left + 8), max(1, bottom - top + 8)), 0)
    draw = ImageDraw.Draw(image)
    draw.text((4 - left, 4 - top), character, fill=255, font=font)
    pixels = image.load()
    filled_pixels = [
        (x, y)
        for y in range(image.height)
        for x in range(image.width)
        if pixels[x, y] > 128
    ]
    if not filled_pixels:
        return tuple(tuple(False for _x in range(width)) for _y in range(height))

    min_x = min(x for x, _y in filled_pixels)
    max_x = max(x for x, _y in filled_pixels)
    min_y = min(y for _x, y in filled_pixels)
    max_y = max(y for _x, y in filled_pixels)
    cropped = image.crop((min_x, min_y, max_x + 1, max_y + 1))
    resampling = getattr(Image, "Resampling", Image).NEAREST
    resized = cropped.resize((width, height), resampling)
    resized_pixels = resized.load()
    return tuple(
        tuple(resized_pixels[x, y] > 128 for x in range(width))
        for y in range(height)
    )


def _bitmap_filled_ratio(bitmap: tuple[tuple[bool, ...], ...]) -> float:
    total = sum(len(row) for row in bitmap)
    if total == 0:
        return 0.0
    return sum(1 for row in bitmap for cell in row if cell) / total


def _glyph_bitmap(
    mask_pixels: set[tuple[int, int]],
    group: ColumnGroup,
    top: int,
    bottom: int,
) -> list[list[bool]]:
    return [
        [(group.start + x, y) in mask_pixels for x in range(group.end - group.start + 1)]
        for y in range(top, bottom + 1)
    ]


def _pattern_bitmap(
    pattern: GlyphPattern,
    *,
    width: int,
    height: int,
) -> list[list[bool]]:
    pattern_height = len(pattern)
    pattern_width = len(pattern[0])
    return [
        [
            pattern[y * pattern_height // height][x * pattern_width // width] == "#"
            for x in range(width)
        ]
        for y in range(height)
    ]


def _bitmap_distance(
    left: list[list[bool]],
    right: list[list[bool]],
) -> float:
    total = 0
    mismatch = 0
    for left_row, right_row in zip(left, right):
        for left_cell, right_cell in zip(left_row, right_row):
            total += 1
            if left_cell != right_cell:
                mismatch += 1
    if total == 0:
        return 1.0
    return mismatch / total


def _structural_glyph_match(pattern: GlyphPattern) -> str | None:
    if _looks_like_uppercase_i(pattern):
        return "I"
    if _looks_like_uppercase_h(pattern):
        return "H"
    if _looks_like_lowercase_l(pattern):
        return "l"
    return None


def _looks_like_uppercase_i(pattern: GlyphPattern) -> bool:
    row_counts = _row_counts(pattern)
    middle_counts = row_counts[1:-1]
    if row_counts[0] < 4 or row_counts[-1] < 4:
        return False
    if any(count > 2 or count == 0 for count in middle_counts):
        return False

    column_counts = _column_counts(pattern)
    center_fill = max(column_counts[1:4])
    edge_fill = column_counts[0] + column_counts[-1]
    return center_fill >= 5 and edge_fill <= 4


def _looks_like_uppercase_h(pattern: GlyphPattern) -> bool:
    row_counts = _row_counts(pattern)
    column_counts = _column_counts(pattern)
    has_side_stems = column_counts[0] >= 6 and column_counts[-1] >= 6
    has_crossbar = any(count >= 4 for count in row_counts[1:-1])
    has_open_center = sum(column_counts[1:-1]) <= 8
    return has_side_stems and has_crossbar and has_open_center


def _looks_like_lowercase_l(pattern: GlyphPattern) -> bool:
    row_counts = _row_counts(pattern)
    if row_counts[-1] < 3 or max(row_counts[:-1]) > 3:
        return False
    if sum(1 for count in row_counts[:-1] if 1 <= count <= 3) < 5:
        return False
    if any(not _has_single_run(row) for row in pattern):
        return False

    column_counts = _column_counts(pattern)
    left_fill = column_counts[0] + column_counts[1]
    right_fill = column_counts[-2] + column_counts[-1]
    return left_fill >= 8 and right_fill <= 5


def _fuzzy_glyph_match(
    pattern: GlyphPattern,
    glyphs: dict[GlyphPattern, str],
    *,
    allowed_characters: set[str] | None = None,
    max_distance: int = FUZZY_GLYPH_MAX_DISTANCE,
    min_margin: int = FUZZY_GLYPH_MIN_MARGIN,
    accept_close_ties: bool = False,
) -> str | None:
    ranked_matches = sorted(
        (_glyph_distance(pattern, candidate), glyph)
        for candidate, glyph in glyphs.items()
        if _same_grid_size(pattern, candidate)
        and _character_allowed(glyph, allowed_characters)
    )
    if not ranked_matches:
        return None
    best_distance, best_glyph = ranked_matches[0]
    second_distance = ranked_matches[1][0] if len(ranked_matches) > 1 else 999

    if best_distance > max_distance:
        return None
    if (
        best_distance > 1
        and second_distance - best_distance < min_margin
        and not (accept_close_ties and best_distance <= 2)
    ):
        return None
    return best_glyph


def _same_grid_size(left: GlyphPattern, right: GlyphPattern) -> bool:
    return len(left) == len(right) and all(
        len(left_row) == len(right_row)
        for left_row, right_row in zip(left, right)
    )


def _glyph_distance(left: GlyphPattern, right: GlyphPattern) -> int:
    return sum(
        left_cell != right_cell
        for left_row, right_row in zip(left, right)
        for left_cell, right_cell in zip(left_row, right_row)
    )


def _row_counts(pattern: GlyphPattern) -> list[int]:
    return [row.count("#") for row in pattern]


def _column_counts(pattern: GlyphPattern) -> list[int]:
    return [
        sum(1 for row in pattern if row[column_index] == "#")
        for column_index in range(5)
    ]


def _has_single_run(row: str) -> bool:
    return row.strip(".").replace("#", "") == ""


def _find_text_pixels(image: Any) -> set[tuple[int, int]]:
    pixels = image.load()
    text_pixels: set[tuple[int, int]] = set()
    for y in range(image.height):
        for x in range(image.width):
            red, green, blue = pixels[x, y]
            brightness = max(red, green, blue)
            saturation = brightness - min(red, green, blue)
            if brightness >= 120 and saturation >= 35:
                text_pixels.add((x, y))
    return text_pixels


def _column_groups(mask_pixels: set[tuple[int, int]]) -> list[ColumnGroup]:
    columns = sorted({x for x, _y in mask_pixels})
    if not columns:
        return []

    groups: list[ColumnGroup] = []
    start = previous = columns[0]
    for column in columns[1:]:
        if column == previous + 1:
            previous = column
            continue
        groups.append(ColumnGroup(start, previous))
        start = previous = column
    groups.append(ColumnGroup(start, previous))
    return groups


def _normal_letter_gap(groups: list[ColumnGroup]) -> float:
    gaps = [
        group.start - previous.end - 1
        for previous, group in zip(groups, groups[1:])
        if group.start - previous.end - 1 > 0
    ]
    if not gaps:
        return 1.0
    return min(gaps)


def _glyph_pattern(
    image: Any,
    mask_pixels: set[tuple[int, int]],
    group: ColumnGroup,
    *,
    grid_width: int = 5,
    grid_height: int = 7,
    top: int | None = None,
    bottom: int | None = None,
) -> GlyphPattern:
    group_pixels = [
        (x, y)
        for x, y in mask_pixels
        if group.start <= x <= group.end
    ]
    if top is None:
        top = min(y for _x, y in group_pixels)
    if bottom is None:
        bottom = max(y for _x, y in group_pixels)
    width = group.end - group.start + 1
    height = bottom - top + 1
    rows: list[str] = []

    for grid_y in range(grid_height):
        row = ""
        y_start = top + grid_y * height // grid_height
        y_end = top + (grid_y + 1) * height // grid_height
        for grid_x in range(grid_width):
            x_start = group.start + grid_x * width // grid_width
            x_end = group.start + (grid_x + 1) * width // grid_width
            total = 0
            text_count = 0
            for y in range(y_start, y_end):
                for x in range(x_start, x_end):
                    total += 1
                    red, green, blue = image.getpixel((x, y))
                    brightness = max(red, green, blue)
                    saturation = brightness - min(red, green, blue)
                    if brightness >= 120 and saturation >= 35:
                        text_count += 1
            row += "#" if total and text_count > total * 0.25 else "."
        rows.append(row)

    return tuple(rows)
