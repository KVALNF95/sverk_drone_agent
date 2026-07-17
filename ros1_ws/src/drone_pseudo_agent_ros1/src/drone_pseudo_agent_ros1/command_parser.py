from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Union


class CommandParseError(ValueError):
    pass


@dataclass(frozen=True)
class InitializeCellCommand:
    cell: str


@dataclass(frozen=True)
class ChessFlightCommand:
    source_cell: str
    target_cell: str


@dataclass(frozen=True)
class RelativeFlightCommand:
    forward_m: float
    left_m: float


@dataclass(frozen=True)
class TakeoffCommand:
    height_m: float | None = None


@dataclass(frozen=True)
class LandCommand:
    pass


@dataclass(frozen=True)
class HoldCommand:
    pass


@dataclass(frozen=True)
class TelemetryCommand:
    pass


@dataclass(frozen=True)
class StatusCommand:
    pass


COMMAND_TYPE = Union[
    InitializeCellCommand,
    ChessFlightCommand,
    RelativeFlightCommand,
    TakeoffCommand,
    LandCommand,
    HoldCommand,
    TelemetryCommand,
    StatusCommand,
]


CELL_RE = r"([a-h][1-8])"
NUMBER_RE = r"([0-9]+(?:[.,][0-9]+)?)"
UNIT_RE = r"(?:\s*(?:метр(?:а|ов)?|м))?"
WHITESPACE_RE = re.compile(r"\s+")
PUNCTUATION_RE = re.compile(r"[!?;:]")
NON_DECIMAL_DOT_RE = re.compile(r"(?<!\d)\.(?!\d)")
SEPARATOR_RE = re.compile(r"(?:,|\s+и\s+|\s+потом\s+|\s+затем\s+|\s+)$")
SEGMENT_RE = re.compile(
    r"(?:^|(?:\s*(?:,|\s+и\s+|\s+затем\s+|\s+потом\s+)))"
    r"(?:на\s+)?"
    + NUMBER_RE
    + UNIT_RE
    + r"\s*(вперед|назад|влево|вправо)"
)


def normalize_text(text: str) -> str:
    cleaned = str(text or "").strip().lower().replace("ё", "е")
    cleaned = PUNCTUATION_RE.sub(" ", cleaned)
    cleaned = NON_DECIMAL_DOT_RE.sub(" ", cleaned)
    cleaned = cleaned.replace("–", "-").replace("—", "-")
    cleaned = WHITESPACE_RE.sub(" ", cleaned)
    return cleaned.strip()


def normalize_cell(cell: str) -> str:
    value = normalize_text(cell)
    if not re.fullmatch(CELL_RE, value):
        raise CommandParseError("Ожидалась клетка в формате a1..h8.")
    return value


def parse_number(raw: str) -> float:
    try:
        return float(str(raw).replace(",", "."))
    except ValueError as exc:
        raise CommandParseError("Не удалось распознать число %r." % raw) from exc


def cell_to_indices(cell: str) -> tuple[int, int]:
    normalized = normalize_cell(cell)
    return ord(normalized[0]) - ord("a"), int(normalized[1])


def chess_delta_m(source_cell: str, target_cell: str, cell_size_m: float, side: str) -> tuple[float, float]:
    source_file, source_rank = cell_to_indices(source_cell)
    target_file, target_rank = cell_to_indices(target_cell)
    delta_rank = target_rank - source_rank
    delta_file = target_file - source_file

    orientation = str(side or "white").strip().lower()
    if orientation not in {"white", "black"}:
        raise CommandParseError("CHESS_SIDE должен быть white или black.")

    if orientation == "white":
        forward_cells = delta_rank
        left_cells = -delta_file
    else:
        forward_cells = -delta_rank
        left_cells = delta_file

    return forward_cells * cell_size_m, left_cells * cell_size_m


def _parse_initialize_cell(text: str) -> InitializeCellCommand | None:
    patterns = (
        r"^я\s+в\s+клетке\s+" + CELL_RE + r"$",
        r"^установи\s+текущую\s+клетку\s+" + CELL_RE + r"$",
        r"^установи\s+клетку\s+" + CELL_RE + r"$",
        r"^текущая\s+клетка\s+" + CELL_RE + r"$",
    )
    for pattern in patterns:
        match = re.fullmatch(pattern, text)
        if match:
            return InitializeCellCommand(cell=normalize_cell(match.group(1)))
    return None


def _parse_chess_flight(text: str) -> ChessFlightCommand | None:
    match = re.fullmatch(r"^прилети\s+из\s+клетки\s+(\S+)\s+в\s+(?:клетку\s+)?(\S+)$", text)
    if not match:
        return None
    return ChessFlightCommand(
        source_cell=normalize_cell(match.group(1)),
        target_cell=normalize_cell(match.group(2)),
    )


def _parse_takeoff(text: str) -> TakeoffCommand | None:
    match = re.fullmatch(r"^взлети(?:\s+на\s+" + NUMBER_RE + UNIT_RE + r")?$", text)
    if not match:
        return None
    height_m = parse_number(match.group(1)) if match.group(1) else None
    return TakeoffCommand(height_m=height_m)


def _parse_relative_flight(text: str) -> RelativeFlightCommand | None:
    if not text.startswith("прилети"):
        return None
    body = text[len("прилети"):].strip()
    if not body:
        raise CommandParseError("После команды 'прилети' нужно указать смещение или клетки.")

    position = 0
    forward_m = 0.0
    left_m = 0.0
    seen_axes: set[str] = set()
    found = False

    while position < len(body):
        match = SEGMENT_RE.match(body, position)
        if not match:
            break
        found = True
        value = parse_number(match.group(1))
        direction = match.group(2)
        if direction in {"вперед", "назад"}:
            if "forward" in seen_axes:
                raise CommandParseError("Ось вперед/назад можно указать только один раз.")
            seen_axes.add("forward")
            forward_m = value if direction == "вперед" else -value
        else:
            if "left" in seen_axes:
                raise CommandParseError("Ось влево/вправо можно указать только один раз.")
            seen_axes.add("left")
            left_m = value if direction == "влево" else -value
        position = match.end()

    tail = body[position:].strip()
    if tail:
        normalized_tail = SEPARATOR_RE.sub("", tail).strip()
        if normalized_tail:
            raise CommandParseError("Не удалось распознать часть команды: %r." % tail)

    if not found:
        return None
    if abs(forward_m) < 1e-9 and abs(left_m) < 1e-9:
        raise CommandParseError("Смещение не должно быть нулевым.")
    return RelativeFlightCommand(forward_m=forward_m, left_m=left_m)


def parse_text_command(text: str) -> COMMAND_TYPE:
    normalized = normalize_text(text)
    if not normalized:
        raise CommandParseError("Пустая команда.")

    for parser in (_parse_initialize_cell, _parse_chess_flight, _parse_takeoff, _parse_relative_flight):
        command = parser(normalized)
        if command is not None:
            return command

    if normalized in {"сядь", "приземлись", "выполни посадку"}:
        return LandCommand()
    if normalized in {"зависни", "остановись", "стой"}:
        return HoldCommand()
    if normalized in {"телеметрия", "сообщи телеметрию"}:
        return TelemetryCommand()
    if normalized in {"статус", "готовность", "системный статус"}:
        return StatusCommand()

    raise CommandParseError(
        "Команда не поддерживается. Поддерживаются: инициализация клетки, шахматный перелет, "
        "относительный перелет, взлет, посадка, зависание, статус и телеметрия."
    )
