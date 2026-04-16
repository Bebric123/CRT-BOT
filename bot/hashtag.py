"""Сопоставление триггер-хештега с текстом поста (целое «слово», без ложных подстрок)."""


def text_has_trigger_hashtag(body: str, hashtag: str) -> bool:
    """True, если в тексте есть именно этот хештег как токен: не #predict_week внутри #predict_weekly."""
    tag = hashtag.strip().lower()
    if not tag.startswith("#"):
        tag = "#" + tag
    if not tag or len(tag) < 2:
        return False
    lower = body.lower()
    start = 0
    while True:
        i = lower.find(tag, start)
        if i == -1:
            return False
        after = i + len(tag)
        if after < len(lower):
            c = lower[after]
            if c.isalnum() or c == "_":
                start = i + 1
                continue
        if i > 0:
            prev = lower[i - 1]
            if prev.isalnum() or prev == "_":
                start = i + 1
                continue
        return True
