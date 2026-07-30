from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from services.codegen.models import DesignParameter


@dataclass(frozen=True)
class DirectParameterEdit:
    name: str
    value: float | int


_EDIT = re.compile(
    r"\b(set|change|make|increase|decrease|reduce|enlarge|shrink|"
    r"ustaw|zmień|zwiększ|zmniejsz|powiększ|pomniejsz|poszerz|zwęż)\b",
    re.IGNORECASE,
)
_AMBIGUOUS = re.compile(
    r"\b(bigger|larger|smaller|stronger|better|more printable|"
    r"większ\w*|mniejsz\w*|mocniejsz\w*|wytrzyma\w*|wytrzymalsz\w*|lepiej drukowal\w*)\b",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")

_STEMS: dict[str, tuple[str, ...]] = {
    "diameter": ("średnic",),
    "width": ("szerokoś",),
    "height": ("wysokoś",),
    "depth": ("głębokoś",),
    "thickness": ("gruboś",),
    "count": ("liczb", "iloś"),
    "hole": ("otwor", "dziur"),
    "holes": ("otwor", "dziur"),
    "wheel": ("kołowrot",),
    "track": ("bieżn",),
    "rung": ("szczebel",),
    "spoke": ("szprych",),
    "wall": ("ściank", "ścian"),
    "base": ("podstaw",),
    "cable": ("kabel",),
    "screw": ("śrub",),
}


def ambiguity_question(message: str) -> str | None:
    normalized = _normalize(message)
    if _NUMBER.search(normalized) or not _AMBIGUOUS.search(normalized):
        return None
    return "Który konkretnie wymiar lub element mam zmienić i do jakiej wartości?"


def parse_direct_parameter_edit(
    message: str,
    parameters: Sequence[DesignParameter],
) -> DirectParameterEdit | None:
    normalized = _normalize(message)
    if not _EDIT.search(normalized) or "%" in message:
        return None
    number_match = _NUMBER.search(normalized)
    if not number_match:
        return None

    scored = [(parameter, _score(normalized, parameter.name)) for parameter in parameters]
    scored = [(parameter, score) for parameter, score in scored if score > 0]
    if not scored:
        return None
    best = max(score for _, score in scored)
    winners = [parameter for parameter, score in scored if score == best]
    if len(winners) != 1:
        return None

    parameter = winners[0]
    numeric = float(number_match.group(0).replace(",", "."))
    if parameter.type == "length_mm" and re.search(r"\b(cm|centymetr\w*)\b", normalized):
        numeric *= 10
    value: float | int = int(numeric) if isinstance(parameter.value, int) and numeric.is_integer() else numeric
    return DirectParameterEdit(name=parameter.name, value=value)


def _normalize(message: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\wąćęłńóśźż%.,-]+", " ", message.lower())).strip()


def _score(message: str, name: str) -> int:
    clean_name = re.sub(r"_(mm|deg)$", "", name.lower())
    spaced = clean_name.replace("_", " ")
    if re.search(rf"\b{re.escape(clean_name)}\b", message) or re.search(rf"\b{re.escape(spaced)}\b", message):
        return 100
    tokens = clean_name.split("_")
    score = 0
    for token in tokens:
        if re.search(rf"\b{re.escape(token)}\b", message):
            score += 12
        if any(stem in message for stem in _STEMS.get(token, ())):
            score += 10
    if "wheel" in tokens and "diameter" in tokens and "kołowrot" in message and "średnic" in message:
        score += 60
    if "hole" in tokens and "diameter" in tokens and "otwor" in message and "średnic" in message:
        score += 60
    if "rung" in tokens and "count" in tokens and "szczebel" in message:
        score += 60
    if "spoke" in tokens and "count" in tokens and "szprych" in message:
        score += 60
    return score


__all__ = ["DirectParameterEdit", "ambiguity_question", "parse_direct_parameter_edit"]
