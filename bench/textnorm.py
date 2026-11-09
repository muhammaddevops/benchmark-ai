"""Bilingual (Arabic / English) text normalization, language detection and error rates."""

from __future__ import annotations

import re
import unicodedata

import jiwer

_TASHKEEL = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")  # diacritics + tatweel
_AR_LETTER = re.compile(r"[ء-يٱ-ۓ]")
_LATIN_LETTER = re.compile(r"[A-Za-z]")
_PUNCT = re.compile(r"[^\w\s]|_", re.UNICODE)
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_ALEF = re.compile(r"[إأآٱ]")


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = t.translate(_AR_DIGITS)
    t = re.sub(r"(?<=\d)[,٬.](?=\d{3}\b)", "", t)  # 20,000 -> 20000
    t = _TASHKEEL.sub("", t)
    t = _ALEF.sub("ا", t)
    t = t.replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")
    t = t.replace("،", " ").replace("؟", " ").replace("؛", " ")
    t = t.lower()
    t = _PUNCT.sub(" ", t)
    # "الـ usage" style prefixes: detach a lone Arabic article from Latin words
    t = re.sub(r"\bال\s+(?=[a-z])", "", t)
    return re.sub(r"\s+", " ", t).strip()


_AR_NUM = (
    "صفر واحد واحده اثنين اثنان ثنين ثلاث ثلاثه اربع اربعه خمس خمسه ست سته سبع سبعه ثمان ثمانيه ثماني تسع تسعه "
    "عشر عشره احدعش احد اثنعش ثلطعش عشرين ثلاثين اربعين خمسين ستين سبعين ثمانين تسعين ميه ميه مايه مئه ميتين مئتين "
    "الف الاف الفين تسعمئه تسعميه ثلاثمئه ثلاثميه خمسمئه خمسميه الرابع عشر"
).split()
_EN_NUM = (
    "zero oh one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred thousand"
).split()
_NUM_WORDS = set(_AR_NUM) | {"و" + w for w in _AR_NUM} | set(_EN_NUM)


def strip_numbers(normalized: str) -> str:
    """Drop digits and number words (both scripts) from normalized text, so a transcript
    that writes "350" for "ثلاث مية وخمسين" is not counted as wrong."""
    toks = [t for t in normalized.split() if not t.isdigit() and t not in _NUM_WORDS]
    return " ".join(toks)


def arabic_ratio(text: str) -> float:
    ar = len(_AR_LETTER.findall(text or ""))
    la = len(_LATIN_LETTER.findall(text or ""))
    return ar / (ar + la) if (ar + la) else 0.0


def detect_lang(text: str) -> str:
    """'ar' | 'en' | 'mixed' | '' from the script of the text."""
    if not text or not text.strip():
        return ""
    r = arabic_ratio(text)
    if r >= 0.7:
        return "ar"
    if r <= 0.15:
        return "en"
    return "mixed"


def lang_matches(expected: str, reply_text: str) -> bool:
    """Did the reply come back in the expected language? Arabic replies may carry
    English terms (ratio >= 0.5); English replies must be essentially Latin-script."""
    if not reply_text or not reply_text.strip():
        return False
    if expected in ("any", "", None):
        return True
    r = arabic_ratio(reply_text)
    if expected == "ar":
        return r >= 0.5
    if expected == "en":
        return r <= 0.15
    return True


def cer(ref: str, hyp: str, numbers: bool = True) -> float | None:
    r, h = normalize(ref), normalize(hyp)
    if not numbers:
        r, h = strip_numbers(r), strip_numbers(h)
    if not r:
        return None
    if not h:
        return 1.0
    return min(1.0, jiwer.cer(r, h))


def wer(ref: str, hyp: str, numbers: bool = True) -> float | None:
    r, h = normalize(ref), normalize(hyp)
    if not numbers:
        r, h = strip_numbers(r), strip_numbers(h)
    if not r:
        return None
    if not h:
        return 1.0
    return min(1.0, jiwer.wer(r, h))
