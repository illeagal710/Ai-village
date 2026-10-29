"""The world: terrain, resources, structures, and the physics of every action.

Nothing in here tells an agent what to do. It only defines what is possible.
"""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field

# --- Terrain -----------------------------------------------------------------

GRASS, FOREST, ROCK, WATER = "grass", "forest", "rock", "water"
TERRAIN_GLYPH = {GRASS: ".", FOREST: "T", ROCK: "^", WATER: "~"}

MAX_WOOD = 6        # trees per forest tile
MAX_STONE = 12      # stone per rock tile (does not regrow)
MAX_BERRIES = 4     # berries per wild bush
FARM_MAX_BERRIES = 8

DAY_LENGTH = 48     # ticks per day
NIGHT_START = 36    # ticks into the day when night falls

# --- Structures ----------------------------------------------------------------
# Each built-in kind has a cost and (optionally) a mechanical effect.
# "other" lets agents build anything they can imagine: they name it,
# describe it and pay whatever materials they choose.

STRUCTURES: dict[str, dict] = {
    "wall": {"cost": {"stone": 2}, "blocks": True, "glyph": "#",
             "effect": "Blocks movement."},
    "path": {"cost": {"stone": 1}, "glyph": "=",
             "effect": "A paved tile. Walking along paths lets you travel further each turn."},
    "house": {"cost": {"wood": 8, "stone": 4}, "glyph": "H",
              "effect": "Resting inside restores energy three times faster."},
    "farm": {"cost": {"wood": 3}, "glyph": "F",
             "effect": "Grows berries steadily (up to 8). Must be on grass."},
    "chest": {"cost": {"wood": 3}, "glyph": "C",
              "effect": "Stores items. Anyone can put items in or take them out."},
    "campfire": {"cost": {"wood": 2, "stone": 1}, "glyph": "&",
                 "effect": "Resting within 2 tiles of a campfire restores energy faster."},
    "bridge": {"cost": {"wood": 4}, "glyph": "b",
               "effect": "Built on water; makes it walkable."},
    "sign": {"cost": {"wood": 1}, "glyph": "!",
             "effect": "Holds written text that anyone nearby can read."},
    "other": {"cost": {}, "glyph": "?",
              "effect": "Anything you imagine. You name it, describe it and choose what materials to put into it."},
}

ITEMS = ("wood", "stone", "berries")
BLOCK_MATERIALS = ("wood", "stone")   # what single blocks can be made of
MAX_HEIGHT = 16                       # highest layer a block can sit on (ground is 0)
CARRY_LIMIT = 30

DIRS = {
    "n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0),
    "ne": (1, -1), "nw": (-1, -1), "se": (1, 1), "sw": (-1, 1),
}


@dataclass
class Structure:
    kind: str
    x: int
    y: int
    builder: str
    built_tick: int
    name: str = ""
    description: str = ""
    text: str = ""                     # for signs
    materials: dict = field(default_factory=dict)
    storage: dict = field(default_factory=dict)   # for chests

    @property
    def glyph(self) -> str:
        return STRUCTURES[self.kind]["glyph"]

    @property
    def blocks(self) -> bool:
        return STRUCTURES[self.kind].get("blocks", False)

    def label(self) -> str:
        title = f'"{self.name}" ' if self.name else ""
        return f"{title}({self.kind})"

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class Tile:
    terrain: str
    wood: int = 0
    stone: int = 0
    berries: int = 0
    structure: Structure | None = None

    def to_dict(self) -> dict:
        d = {"terrain": self.terrain, "wood": self.wood, "stone": self.stone, "berries": self.berries}
        d["structure"] = self.structure.to_dict() if self.structure else None
        return d


class World:
    def __init__(self, width: int = 48, height: int = 32, seed: int | None = None):
        self.width, self.height = width, height
        self.seed = seed if seed is not None else random.randrange(1 << 30)
        self.rng = random.Random(self.seed)
        self.tick = 0
        self.tiles: list[list[Tile]] = []
        self.events: deque[dict] = deque(maxlen=300)   # global log for the viewer
        self.blocks: dict[tuple[int, int, int], str] = {}   # (x, y, z) -> material; z=1 sits on the ground
        self._generate()

    # --- generation ----------------------------------------------------------

    def _noise(self, scale: int) -> list[list[float]]:
        """Cheap smooth noise: random grid, upscaled with bilinear interpolation."""
        gw, gh = self.width // scale + 2, self.height // scale + 2
        grid = [[self.rng.random() for _ in range(gw)] for _ in range(gh)]
        out = []
        for y in range(self.height):
            row = []
            for x in range(self.width):
                gx, gy = x / scale, y / scale
                x0, y0 = int(gx), int(gy)
                fx, fy = gx - x0, gy - y0
                a = grid[y0][x0] * (1 - fx) + grid[y0][x0 + 1] * fx
                b = grid[y0 + 1][x0] * (1 - fx) + grid[y0 + 1][x0 + 1] * fx
                row.append(a * (1 - fy) + b * fy)
            out.append(row)
        return out

    def _generate(self) -> None:
        height = self._noise(8)
        moisture = self._noise(5)
        for y in range(self.height):
            row = []
            for x in range(self.width):
                h, m = height[y][x], moisture[y][x]
                if h < 0.28:
                    tile = Tile(WATER)
                elif h > 0.75:
                    tile = Tile(ROCK, stone=MAX_STONE)
                elif m > 0.58:
                    tile = Tile(FOREST, wood=self.rng.randint(2, MAX_WOOD))
                else:
                    tile = Tile(GRASS)
                    if self.rng.random() < 0.06:
                        tile.berries = self.rng.randint(1, MAX_BERRIES)
                row.append(tile)
            self.tiles.append(row)

    # --- queries -------------------------------------------------------------

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def tile(self, x: int, y: int) -> Tile:
        return self.tiles[y][x]

    def passable(self, x: int, y: int) -> bool:
        if not self.in_bounds(x, y):
            return False
        if (x, y, 1) in self.blocks:   # a block at ground level is in the way; higher ones can be walked under
            return False
        t = self.tile(x, y)
        if t.structure:
            if t.structure.blocks:
                return False
            if t.structure.kind == "bridge":
                return True
        return t.terrain != WATER

    @property
    def day(self) -> int:
        return self.tick // DAY_LENGTH + 1

    @property
    def is_night(self) -> bool:
        return self.tick % DAY_LENGTH >= NIGHT_START

    def time_of_day(self) -> str:
        t = self.tick % DAY_LENGTH
        if t < 6:
            return "dawn"
        if t < 18:
            return "morning"
        if t < 30:
            return "afternoon"
        if t < NIGHT_START:
            return "evening"
        return "night"

    def column(self, x: int, y: int) -> list[tuple[int, str]]:
        return sorted((z, m) for (bx, by, z), m in self.blocks.items() if (bx, by) == (x, y))

    def supported(self, x: int, y: int, z: int) -> bool:
        """A block needs the ground, a block under it, or a block beside it to hold on to."""
        if z == 1 or (x, y, z - 1) in self.blocks:
            return True
        return any((x + dx, y + dy, z) in self.blocks for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))

    def random_open_tile(self) -> tuple[int, int]:
        for _ in range(10_000):
            x, y = self.rng.randrange(self.width), self.rng.randrange(self.height)
            if self.tile(x, y).terrain == GRASS and not self.tile(x, y).structure:
                return x, y
        raise RuntimeError("no open land")

    def path(self, start: tuple[int, int], goal: tuple[int, int], occupied: set) -> list[tuple[int, int]]:
        """Breadth-first path from start toward goal. If the goal itself is not
        walkable, returns a path to the nearest reachable neighbour of it."""
        if start == goal:
            return []
        goals = {goal} if self.passable(*goal) else {
            (goal[0] + dx, goal[1] + dy) for dx, dy in DIRS.values() if self.passable(goal[0] + dx, goal[1] + dy)
        }
        if not goals:
            return []
        prev = {start: None}
        q = deque([start])
        found = None
        while q:
            cur = q.popleft()
            if cur in goals:
                found = cur
                break
            if len(prev) > 4000:
                break
            for dx, dy in DIRS.values():
                nxt = (cur[0] + dx, cur[1] + dy)
                if nxt in prev or not self.passable(*nxt):
                    continue
                if nxt in occupied and nxt not in goals:
                    continue
                prev[nxt] = cur
                q.append(nxt)
        if found is None:
            return []
        steps = []
        while found != start:
            steps.append(found)
            found = prev[found]
        return steps[::-1]

    # --- time ----------------------------------------------------------------

    def step_nature(self) -> None:
        """Regrowth. Forests and bushes recover slowly; farms grow faster."""
        self.tick += 1
        for row in self.tiles:
            for t in row:
                s = t.structure
                if s and s.kind == "farm":
                    if t.berries < FARM_MAX_BERRIES and self.rng.random() < 0.25:
                        t.berries += 1
                elif t.terrain == FOREST and t.wood < MAX_WOOD and self.rng.random() < 0.01:
                    t.wood += 1
                elif t.terrain == GRASS and not s and self.rng.random() < 0.0003:
                    t.berries = min(MAX_BERRIES, t.berries + 1)
                elif t.terrain == GRASS and 0 < t.berries < MAX_BERRIES and self.rng.random() < 0.03:
                    t.berries += 1

    def log(self, who: str, text: str, kind: str = "action") -> None:
        self.events.append({"tick": self.tick, "who": who, "text": text, "kind": kind})

    # --- persistence ---------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "width": self.width, "height": self.height, "seed": self.seed, "tick": self.tick,
            "tiles": [[t.to_dict() for t in row] for row in self.tiles],
            "events": list(self.events),
            "blocks": [[x, y, z, m] for (x, y, z), m in self.blocks.items()],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "World":
        w = cls.__new__(cls)
        w.width, w.height, w.seed, w.tick = d["width"], d["height"], d["seed"], d["tick"]
        w.rng = random.Random(w.seed + w.tick)
        w.events = deque(d.get("events", []), maxlen=300)
        w.blocks = {(x, y, z): m for x, y, z, m in d.get("blocks", [])}
        w.tiles = []
        for row in d["tiles"]:
            out = []
            for td in row:
                sd = td.pop("structure")
                t = Tile(**td)
                if sd:
                    t.structure = Structure(**sd)
                out.append(t)
            w.tiles.append(out)
        return w
