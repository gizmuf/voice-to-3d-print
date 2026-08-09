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
_TARGET_NUMBER = re.compile(r"\b(?:na|to)\s*(-?\d+(?:[.,]\d+)?)\b", re.IGNORECASE)
_PERCENT = re.compile(r"(-?\d+(?:[.,]\d+)?)\s*%")
_INCREASE = re.compile(r"\b(?:increase|enlarge|raise|zwiększ|powiększ|poszerz)\w*\b", re.IGNORECASE)
_DECREASE = re.compile(r"\b(?:decrease|reduce|shrink|lower|zmniejsz|pomniejsz|zwęż)\w*\b", re.IGNORECASE)

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
    edits = parse_direct_parameter_edits(message, parameters)
    return edits[0] if len(edits) == 1 else None


def parse_direct_parameter_edits(
    message: str,
    parameters: Sequence[DesignParameter],
) -> list[DirectParameterEdit]:
    """Parse one or more explicit edits that do not need model reasoning.

    Conjunction-separated requests ("height 35 and width 80") are rebuilt in
    one batch. Relative percentages are accepted only with an explicit
    increase/decrease verb, avoiding the dangerous interpretation of "50%" as
    an absolute length.
    """
    normalized = _normalize(message)
    if not _EDIT.search(normalized):
        return []

    percent = _PERCENT.search(normalized)
    if percent:
        direction = 1 if _INCREASE.search(normalized) else -1 if _DECREASE.search(normalized) else 0
        if direction == 0:
            return []
        parameter = _unique_best_parameter(normalized, parameters)
        if parameter is None or isinstance(parameter.value, (bool, str)):
            return []
        factor = 1.0 + direction * float(percent.group(1).replace(",", ".")) / 100.0
        numeric = float(parameter.value) * factor
        value: float | int = int(round(numeric)) if isinstance(parameter.value, int) else numeric
        return [DirectParameterEdit(name=parameter.name, value=value)]

    clauses = [part.strip() for part in re.split(r"\s+(?:i|oraz|and)\s+|;", normalized) if part.strip()]
    edits: list[DirectParameterEdit] = []
    inherited_verb = bool(_EDIT.search(normalized))
    for clause in clauses:
        edit = _parse_absolute_clause(clause, parameters, allow_without_verb=inherited_verb)
        if edit and all(existing.name != edit.name for existing in edits):
            edits.append(edit)
    return edits


def _parse_absolute_clause(
    normalized: str,
    parameters: Sequence[DesignParameter],
    *,
    allow_without_verb: bool,
) -> DirectParameterEdit | None:
    if not allow_without_verb and not _EDIT.search(normalized):
        return None
    target_matches = list(_TARGET_NUMBER.finditer(normalized))
    number_match = target_matches[-1] if target_matches else _NUMBER.search(normalized)
    if not number_match:
        return None
    parameter = _unique_best_parameter(normalized, parameters)
    if parameter is None:
        return None
    number_text = number_match.group(1) if target_matches else number_match.group(0)
    numeric = float(number_text.replace(",", "."))
    if parameter.type == "length_mm" and re.search(r"\b(cm|centymetr\w*)\b", normalized):
        numeric *= 10
    value: float | int = int(numeric) if isinstance(parameter.value, int) and numeric.is_integer() else numeric
    return DirectParameterEdit(name=parameter.name, value=value)


def _unique_best_parameter(
    normalized: str,
    parameters: Sequence[DesignParameter],
) -> DesignParameter | None:
    scored = [(parameter, _score(normalized, parameter.name)) for parameter in parameters]
    scored = [(parameter, score) for parameter, score in scored if score > 0]
    if not scored:
        return None
    best = max(score for _, score in scored)
    winners = [parameter for parameter, score in scored if score == best]
    return winners[0] if len(winners) == 1 else None


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


__all__ = [
    "DirectParameterEdit",
    "ambiguity_question",
    "parse_direct_parameter_edit",
    "parse_direct_parameter_edits",
]
