"""An agent's body and senses: needs, inventory, memory, and what it perceives.

Agents get no goals. Their perception is plain facts about their surroundings
and their own body.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .world import CARRY_LIMIT, DIRS, STRUCTURES, TERRAIN_GLYPH

if TYPE_CHECKING:
    from .sim import Simulation

DAY_VISION, NIGHT_VISION = 6, 3
HEARING_RANGE = 10
MAX_MEMORY, MAX_NOTES = 25, 30


@dataclass
class Agent:
    id: int
    x: int
    y: int
    name: str | None = None
    satiety: float = 80.0
    energy: float = 80.0
    inventory: dict = field(default_factory=dict)
    memory: deque = field(default_factory=lambda: deque(maxlen=MAX_MEMORY))
    notes: list = field(default_factory=list)
    inbox: list = field(default_factory=list)
    last_action: str = ""
    last_thought: str = ""
    collapsed: bool = False

    @property
    def label(self) -> str:
        return self.name or f"unnamed being #{self.id}"

    @property
    def pos(self) -> tuple[int, int]:
        return self.x, self.y

    @property
    def symbol(self) -> str:
        return str(self.id % 10)

    def carried(self) -> int:
        return sum(self.inventory.values())

    def add(self, item: str, n: int) -> int:
        """Add up to n items, respecting the carry limit. Returns how many were added."""
        n = max(0, min(n, CARRY_LIMIT - self.carried()))
        if n:
            self.inventory[item] = self.inventory.get(item, 0) + n
        return n

    def remove(self, item: str, n: int) -> bool:
        if self.inventory.get(item, 0) < n:
            return False
        self.inventory[item] -= n
        if not self.inventory[item]:
            del self.inventory[item]
        return True

    def remember_event(self, tick: int, text: str) -> None:
        self.memory.append(f"[tick {tick}] {text}")

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items()}
        d["memory"] = list(self.memory)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Agent":
        d = dict(d)
        d["memory"] = deque(d.get("memory", []), maxlen=MAX_MEMORY)
        return cls(**d)


def _need_word(v: float) -> str:
    if v >= 75:
        return "good"
    if v >= 45:
        return "okay"
    if v >= 20:
        return "low"
    return "very low"


def perceive(sim: "Simulation", agent: Agent) -> str:
    """Render what an agent senses right now as plain text."""
    w = sim.world
    r = NIGHT_VISION if w.is_night else DAY_VISION
    others = {a.pos: a for a in sim.agents if a is not agent}

    lines = [f"Tick {w.tick}. Day {w.day}, {w.time_of_day()}."]
    lines.append(f"You are {agent.label}. You stand at ({agent.x}, {agent.y}) in a world {w.width} wide and {w.height} tall.")
    if not agent.name:
        lines.append("You have no name.")
    lines.append(f"Fullness {agent.satiety:.0f}/100 ({_need_word(agent.satiety)}). Energy {agent.energy:.0f}/100 ({_need_word(agent.energy)}).")
    if agent.collapsed:
        lines.append("You collapsed from exhaustion and could not act last turn.")
    inv = ", ".join(f"{k} {v}" for k, v in sorted(agent.inventory.items())) or "nothing"
    lines.append(f"Carrying: {inv} ({agent.carried()}/{CARRY_LIMIT}).")

    # Map
    lines.append("")
    lines.append(f"What you can see (radius {r}). Legend: . grass, T forest, ^ rock, ~ water, * berries, @ you, digits = other beings, other symbols = structures.")
    x0, x1 = max(0, agent.x - r), min(w.width - 1, agent.x + r)
    y0, y1 = max(0, agent.y - r), min(w.height - 1, agent.y + r)
    lines.append("     " + "".join(f"{x % 100:>3}" for x in range(x0, x1 + 1)))
    seen_structures, seen_beings, resources = [], [], []
    for y in range(y0, y1 + 1):
        row = []
        for x in range(x0, x1 + 1):
            t = w.tile(x, y)
            if (x, y) == agent.pos:
                ch = "@"
            elif (x, y) in others:
                ch = others[(x, y)].symbol
                seen_beings.append(others[(x, y)])
            elif t.structure:
                ch = t.structure.glyph
            elif t.berries:
                ch = "*"
            else:
                ch = TERRAIN_GLYPH[t.terrain]
            if t.structure:
                seen_structures.append(t.structure)
            if max(abs(x - agent.x), abs(y - agent.y)) <= 1:
                bits = []
                if t.wood:
                    bits.append(f"wood {t.wood}")
                if t.stone:
                    bits.append(f"stone {t.stone}")
                if t.berries:
                    bits.append(f"berries {t.berries}")
                if bits:
                    resources.append(f"({x}, {y}) {t.terrain}: " + ", ".join(bits))
            row.append(f"{ch:>3}")
        lines.append(f"{y:>4} " + "".join(row))

    if resources:
        lines.append("")
        lines.append("Within reach: " + "; ".join(resources) + ".")

    if seen_structures:
        lines.append("")
        lines.append("Structures you can see:")
        for s in seen_structures:
            desc = f' - "{s.description}"' if s.description else ""
            line = f"- ({s.x}, {s.y}) {s.label()} built by {s.builder} on tick {s.built_tick}{desc}"
            if s.kind == "sign":
                line += f'. It reads: "{s.text}"' if s.text else ". It is blank"
            if s.kind == "chest":
                contents = ", ".join(f"{k} {v}" for k, v in s.storage.items() if v) or "empty"
                line += f". Contains: {contents}"
            lines.append(line)

    if seen_beings:
        lines.append("")
        lines.append("Beings you can see:")
        for b in seen_beings:
            lines.append(f"- [{b.symbol}] {b.label} at ({b.x}, {b.y})" + (f", last seen: {b.last_action}" if b.last_action else ""))

    if agent.inbox:
        lines.append("")
        lines.append("You heard:")
        lines.extend(f"- {m}" for m in agent.inbox)

    if agent.memory:
        lines.append("")
        lines.append("Your recent past:")
        lines.extend(f"- {m}" for m in agent.memory)

    if agent.last_thought:
        lines.append("")
        lines.append(f'Last turn you were thinking: "{agent.last_thought}"')

    if agent.notes:
        lines.append("")
        lines.append("Your notes to yourself:")
        lines.extend(f"{i + 1}. {n}" for i, n in enumerate(agent.notes))

    return "\n".join(lines)


def neighbours(x: int, y: int):
    yield x, y
    for dx, dy in DIRS.values():
        yield x + dx, y + dy


def structure_summary() -> str:
    out = []
    for kind, spec in STRUCTURES.items():
        cost = ", ".join(f"{n} {item}" for item, n in spec["cost"].items()) or "materials of your choice"
        out.append(f"- {kind} ({spec['glyph']}): costs {cost}. {spec['effect']}")
    return "\n".join(out)
