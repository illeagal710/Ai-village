"""The simulation loop: perceive, decide (in parallel), act, let time pass, record."""

from __future__ import annotations

import json
import logging
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import actions
from .agent import Agent, perceive
from .brains import Brain
from .world import TERRAIN_GLYPH, World

log = logging.getLogger(__name__)

HUNGER_PER_TICK = 0.7
FATIGUE_PER_TICK = 0.4
STARVING_DRAIN = 2.0


class Simulation:
    def __init__(self, world: World, agents: list[Agent], brain: Brain, run_dir: Path | None = None):
        self.world = world
        self.agents = agents
        self.brain = brain
        self.run_dir = Path(run_dir) if run_dir else None
        self.lock = threading.Lock()
        self.latest_frame: dict | None = None
        self._pool = ThreadPoolExecutor(max_workers=max(1, len(agents)))
        if self.run_dir:
            self.run_dir.mkdir(parents=True, exist_ok=True)
        self.latest_frame = self.frame([])

    @classmethod
    def new(cls, brain: Brain, n_agents: int = 6, width: int = 48, height: int = 32,
            seed: int | None = None, run_dir: Path | None = None) -> "Simulation":
        world = World(width, height, seed)
        agents = []
        taken = set()
        # Agents start near each other so they can meet.
        cx, cy = world.random_open_tile()
        for i in range(1, n_agents + 1):
            for _ in range(500):
                x = min(width - 1, max(0, cx + world.rng.randint(-5, 5)))
                y = min(height - 1, max(0, cy + world.rng.randint(-5, 5)))
                if world.passable(x, y) and (x, y) not in taken:
                    break
            else:
                x, y = world.random_open_tile()
            taken.add((x, y))
            agents.append(Agent(id=i, x=x, y=y))
        return cls(world, agents, brain, run_dir)

    # --- one tick ------------------------------------------------------------

    def step(self) -> list[dict]:
        w = self.world
        perceptions = {a.id: perceive(self, a) for a in self.agents}
        for a in self.agents:
            a.inbox.clear()

        active = [a for a in self.agents if not a.collapsed]
        futures = {a.id: self._pool.submit(self.brain.decide, self, a, perceptions[a.id]) for a in active}
        decisions = {}
        for aid, fut in futures.items():
            try:
                decisions[aid] = fut.result()
            except Exception as exc:
                log.exception("brain crashed")
                decisions[aid] = ("rest", {}, f"(confused: {exc})")

        tick_events = []
        order = list(self.agents)
        random.shuffle(order)
        with self.lock:
            for a in order:
                if a.collapsed:
                    a.collapsed = False
                    a.energy = max(a.energy, 15.0)
                    a.last_action = "lying collapsed"
                    a.remember_event(w.tick, "You were collapsed and could not act.")
                    continue
                name, args, thought = decisions[a.id]
                a.last_thought = thought[:500]
                try:
                    result = actions.apply(self, a, name, args)
                    ok = True
                except actions.ActionError as exc:
                    result = f"you tried to {name.replace('_', ' ')} but {exc}"
                    ok = False
                a.last_action = _describe(name, args, ok)
                a.remember_event(w.tick, result[0].upper() + result[1:] + ".")
                ev = {"tick": w.tick, "who": a.label, "id": a.id, "action": name, "args": args,
                      "ok": ok, "result": result, "thought": a.last_thought}
                tick_events.append(ev)
                if name != "say":
                    w.log(a.label, result, kind="action" if ok else "fail")

            self._upkeep()
            w.step_nature()
            frame = self.frame(tick_events)
            self.latest_frame = frame
        self._record(frame)
        return tick_events

    def _upkeep(self) -> None:
        for a in self.agents:
            a.satiety = max(0.0, a.satiety - HUNGER_PER_TICK)
            a.energy -= FATIGUE_PER_TICK + (STARVING_DRAIN if a.satiety <= 0 else 0)
            if a.energy <= 0:
                a.energy = 0.0
                a.collapsed = True
                self.world.log(a.label, "collapsed from exhaustion", kind="fail")

    # --- recording -----------------------------------------------------------

    def frame(self, tick_events: list[dict]) -> dict:
        """A compact snapshot of everything visible, used by the viewer and the replay."""
        w = self.world
        rows, structures = [], []
        for row in w.tiles:
            chars = []
            for t in row:
                chars.append("*" if t.berries and not t.structure else TERRAIN_GLYPH[t.terrain])
                if t.structure:
                    s = t.structure
                    structures.append({"kind": s.kind, "x": s.x, "y": s.y, "name": s.name, "builder": s.builder,
                                       "description": s.description, "text": s.text, "storage": s.storage,
                                       "built_tick": s.built_tick})
            rows.append("".join(chars))
        return {
            "tick": w.tick, "day": w.day, "time": w.time_of_day(), "night": w.is_night,
            "width": w.width, "height": w.height, "terrain": rows, "structures": structures,
            "agents": [{"id": a.id, "name": a.label, "x": a.x, "y": a.y, "satiety": round(a.satiety),
                        "energy": round(a.energy), "inventory": a.inventory, "action": a.last_action,
                        "thought": a.last_thought, "notes": a.notes} for a in self.agents],
            "events": tick_events,
        }

    def _record(self, frame: dict) -> None:
        if not self.run_dir:
            return
        with open(self.run_dir / "history.jsonl", "a") as f:
            f.write(json.dumps(frame, separators=(",", ":")) + "\n")
        if self.world.tick % 10 == 0:
            self.save(self.run_dir / "world.json")

    # --- persistence ---------------------------------------------------------

    def save(self, path: Path) -> None:
        data = {"world": self.world.to_dict(), "agents": [a.to_dict() for a in self.agents]}
        tmp = Path(path).with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path, brain: Brain, run_dir: Path | None = None) -> "Simulation":
        data = json.loads(Path(path).read_text())
        world = World.from_dict(data["world"])
        agents = [Agent.from_dict(d) for d in data["agents"]]
        return cls(world, agents, brain, run_dir)


def _describe(name: str, args: dict, ok: bool) -> str:
    if name == "say":
        text = f'said "{str(args.get("message", ""))[:80]}"'
    elif name == "build":
        what = args.get("name") or args.get("kind")
        text = f"building {what} at ({args.get('x')}, {args.get('y')})"
    elif name == "move_to":
        text = f"walking to ({args.get('x')}, {args.get('y')})"
    elif name in ("gather", "demolish", "store", "take", "write"):
        text = f"{name} at ({args.get('x')}, {args.get('y')})"
    elif name == "set_name":
        text = f"took the name {args.get('name')}"
    else:
        text = name.replace("_", " ")
    return text if ok else f"tried {text} (failed)"
