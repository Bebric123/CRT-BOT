"""Грубая эвристика русского мата (подстроки после нормализации ё→е)."""

from __future__ import annotations

# Короткие «еб*» без контекста не используем — много ложных срабатываний в обычных словах.
_RU_OBSCENE_FRAGMENTS: frozenset[str] = frozenset(
    {
        "бляд",
        "блят",
        "пизд",
        "хуй",
        "хуя",
        "хую",
        "хуе",
        "хуи",
        "хуё",
        "нахуй",
        "похуй",
        "нихуя",
        "нихуй",
        "схуя",
        "схуи",
        "охуел",
        "ахуел",
        "охует",
        "ахует",
        "охуен",
        "ахуен",
        "охуя",
        "ахуя",
        "охуе",
        "ахуе",
        "хуйн",
        "хуев",
        "хуёв",
        "хуяр",
        "хуяч",
        "заеб",
        "уеб",
        "выеб",
        "отъеб",
        "подъеб",
        "приъеб",
        "наеб",
        "ёбан",
        "ебан",
        "ебал",
        "ебат",
        "ебёт",
        "ебет",
        "ебен",
        "ебну",
        "ёбну",
        "ёбн",
        "мудак",
        "мудач",
        "залуп",
        "гандон",
        "шлюх",
        "пидор",
        "пидр",
        "мраз",
        "ублюд",
        "хуесос",
        "хуило",
        "хуила",
        "хуил",
        "сука",
        "суки",
        "суке",
        "сукин",
        "сучк",
        "сучь",
        "еблан",
        "ёблан",
        "говно",
        "говен",
        "сран",
        "дерьм",
        "херн",
        "пидар",
        "чмо",
        "чмош",
    }
)

# Латиница / транслит в подписях и на картинках (OCR часто даёт латиницу).
_LATIN_OBSCENE_FRAGMENTS: frozenset[str] = frozenset(
    {
        "suka",
        "blyat",
        "bliat",
        "pizd",
        "hui",
        "huy",
        "nahui",
        "ebal",
        "eblo",
        "ebat",
        "pidor",
        "pidr",
        "zaeb",
        "hue",
        "huj",
    }
)

# Латинские буквы, похожие на кириллицу (xуй, huy→нуу и т.п. — частично ловим обход).
_HOMOGLYPH_LATIN_TO_CYRILLIC = str.maketrans(
    {
        "a": "а",
        "A": "А",
        "e": "е",
        "E": "Е",
        "o": "о",
        "O": "О",
        "p": "р",
        "P": "Р",
        "c": "с",
        "C": "С",
        "x": "х",
        "X": "х",
        "y": "у",
        "Y": "У",
        "k": "к",
        "K": "К",
        "m": "м",
        "M": "М",
        "T": "Т",
        "t": "т",
        "B": "В",
    }
)


def normalize_for_ru_obscene_scan(text: str) -> str:
    t = text.lower().replace("ё", "е")
    for ch in ("\u200b", "\ufe0f", "\xa0"):
        t = t.replace(ch, "")
    return t


def text_contains_russian_obscene(text: str) -> bool:
    if not text or not text.strip():
        return False
    low = normalize_for_ru_obscene_scan(text)
    if any(s in low for s in _RU_OBSCENE_FRAGMENTS):
        return True
    if any(s in low for s in _LATIN_OBSCENE_FRAGMENTS):
        return True
    homo = normalize_for_ru_obscene_scan(text.translate(_HOMOGLYPH_LATIN_TO_CYRILLIC))
    if homo != low and any(s in homo for s in _RU_OBSCENE_FRAGMENTS):
        return True
    return False
