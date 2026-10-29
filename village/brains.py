"""Minds for the agents.

ClaudeBrain asks Claude what to do, given only the laws of the world and what
the agent perceives. It is never given a goal, a role or a personality.

OfflineBrain is a simple needs-driven heuristic so the world can run (and be
tested) without an API key.
"""

from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING

from .actions import TOOLS
from .agent import Agent, neighbours, structure_summary
from .world import CARRY_LIMIT, DAY_LENGTH, FOREST, ROCK, STRUCTURES

if TYPE_CHECKING:
    from .sim import Simulation

log = logging.getLogger(__name__)

Decision = tuple[str, dict, str]   # (action name, arguments, inner thought)

DEFAULT_MODEL = "claude-opus-5-5"

# The laws of the world. Deliberately no goals, no roles, no suggestions.
SYSTEM_PROMPT = f"""You are a being living in a small two-dimensional world made of tiles. Other beings live here too.

Nobody will tell you what to do. There is no goal and no task. What you do with your existence is up to you.

How the world works:
- Each turn you take exactly one action by calling one of your tools. Time passes between turns; a day lasts {DAY_LENGTH} turns and nights are darker, so you see less.
- Your body has fullness and energy, both out of 100. Fullness drops over time; eating berries restores it. Energy drops over time and with work; resting restores it. If fullness reaches 0 your energy drains fast. If energy reaches 0 you collapse and lose a turn.
- You can carry up to {CARRY_LIMIT} items. The materials in this world are wood (from forests), stone (from rock) and berries (from bushes and farms). Forests and bushes slowly regrow; rock does not.
- You can act on your own tile or any of the 8 tiles around it. Coordinates are (x, y); x grows to the east, y grows to the south.
- You can build. Built things stay in the world until someone tears them down, and everyone can see and use them. Structures you know how to make:
{structure_summary()}
- You can speak; beings within 10 tiles hear you. You can write on signs. You can give things to beings next to you.
- You only remember what is listed under "Your recent past" and "Your notes to yourself". Write notes for anything you want to keep.

Each turn you will be told what you perceive. You may think briefly in plain text, then call exactly one tool."""


class Brain:
    def decide(self, sim: "Simulation", agent: Agent, perception: str) -> Decision:
        raise NotImplementedError


class ClaudeBrain(Brain):
    def __init__(self, model: str = DEFAULT_MODEL, effort: str = "low", fallbacks: bool = True):
        import anthropic

        self.client = anthropic.Anthropic()
        self.model = model
        self.effort = effort
        self.fallbacks = fallbacks

    def decide(self, sim, agent, perception):
        kwargs = dict(
            model=self.model,
            max_tokens=4000,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            tools=TOOLS,
            tool_choice={"type": "auto", "disable_parallel_tool_use": True},
            output_config={"effort": self.effort},
            messages=[{"role": "user", "content": perception}],
        )
        if self.fallbacks:
            kwargs.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        try:
            resp = self.client.beta.messages.create(**kwargs)
        except Exception as exc:  # network trouble, rate limits after SDK retries, etc.
            log.warning("Claude call failed for %s: %s", agent.label, exc)
            return "rest", {}, f"(could not think: {type(exc).__name__})"

        if resp.stop_reason == "refusal":
            return "rest", {}, ""
        thought = " ".join(b.text for b in resp.content if b.type == "text").strip()
        for block in resp.content:
            if block.type == "tool_use":
                return block.name, dict(block.input or {}), thought
        return "rest", {}, thought


class OfflineBrain(Brain):
    """A small needs-driven mind: eat when hungry, rest when tired, otherwise
    gather, build, wander and chat. Good enough to keep the world moving."""

    GREETINGS = ["Hello!", "Nice day.", "Anyone know where the berries are?", "I'm building something.",
                 "This place is growing.", "Good to see you.", "The forest is thinning out."]
    SIGNS = ["Welcome", "Berries nearby", "Home", "Rest here", "Built together", "Keep out", "Hello, stranger"]

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)

    def _nearest(self, sim, agent, test, radius=12):
        best, bd = None, 1e9
        w = sim.world
        for y in range(max(0, agent.y - radius), min(w.height, agent.y + radius + 1)):
            for x in range(max(0, agent.x - radius), min(w.width, agent.x + radius + 1)):
                if test(w.tile(x, y)):
                    d = max(abs(x - agent.x), abs(y - agent.y))
                    if d < bd:
                        best, bd = (x, y), d
        return best, bd

    def _gather_or_go(self, sim, agent, test, why):
        spot, d = self._nearest(sim, agent, test)
        if spot is None:
            return self._wander(sim, agent)
        if d <= 1:
            return "gather", {"x": spot[0], "y": spot[1]}, why
        return "move_to", {"x": spot[0], "y": spot[1]}, why

    def _wander(self, sim, agent):
        w = sim.world
        x = min(w.width - 1, max(0, agent.x + self.rng.randint(-6, 6)))
        y = min(w.height - 1, max(0, agent.y + self.rng.randint(-6, 6)))
        return "move_to", {"x": x, "y": y}, "I feel like exploring."

    def _free_spot(self, sim, agent, terrain_ok=lambda t: t.terrain != "water"):
        occupied = {a.pos for a in sim.agents}
        spots = [(x, y) for x, y in neighbours(agent.x, agent.y)
                 if sim.world.in_bounds(x, y) and (x, y) not in occupied
                 and not sim.world.tile(x, y).structure and terrain_ok(sim.world.tile(x, y))]
        return self.rng.choice(spots) if spots else None

    def decide(self, sim, agent, perception):
        inv = agent.inventory
        if not agent.name and self.rng.random() < 0.5:
            name = self.rng.choice(["Ash", "Bram", "Cleo", "Dov", "Esme", "Finn", "Gale", "Hollis", "Ivo", "Juno"])
            return "set_name", {"name": f"{name}{agent.id}"}, "I should have a name."
        if agent.satiety < 45:
            if inv.get("berries"):
                return "eat", {"amount": 3}, "I'm hungry."
            return self._gather_or_go(sim, agent, lambda t: t.berries > 0, "I need food.")
        if agent.energy < 25:
            return "rest", {}, "I'm tired."
        if agent.inbox and self.rng.random() < 0.4:
            return "say", {"message": self.rng.choice(self.GREETINGS)}, "Someone spoke to me."

        roll = self.rng.random()
        if roll < 0.25 and agent.carried() < CARRY_LIMIT - 2:
            want = self.rng.choice(["wood", "wood", "stone", "berries"])
            test = {"wood": lambda t: t.terrain == FOREST and t.wood > 0,
                    "stone": lambda t: t.terrain == ROCK and t.stone > 0,
                    "berries": lambda t: t.berries > 0}[want]
            return self._gather_or_go(sim, agent, test, f"Collecting {want}.")
        if roll < 0.55:
            affordable = [k for k, s in STRUCTURES.items()
                          if k not in ("other", "bridge") and all(inv.get(i, 0) >= n for i, n in s["cost"].items())]
            # Signs and paths are cheap; keep them from crowding everything else out.
            affordable = [k for k in affordable if k not in ("sign", "path", "wall") or self.rng.random() < 0.15]
            if affordable:
                kind = self.rng.choice(affordable)
                ok = (lambda t: t.terrain == "grass") if kind == "farm" else (lambda t: t.terrain != "water")
                spot = self._free_spot(sim, agent, ok)
                if spot:
                    args = {"kind": kind, "x": spot[0], "y": spot[1]}
                    if kind == "sign":
                        args["text"] = self.rng.choice(self.SIGNS)
                    return "build", args, f"I'll build a {kind}."
            if inv.get("wood", 0) + inv.get("stone", 0) >= 6 and self.rng.random() < 0.15:
                spot = self._free_spot(sim, agent)
                if spot:
                    mats = {k: inv[k] // 2 for k in ("wood", "stone") if inv.get(k, 0) >= 2}
                    if mats:
                        return "build", {"kind": "other", "x": spot[0], "y": spot[1], "name": "Cairn",
                                         "description": "A pile of things, for no reason.", "materials": mats}, "Let's make something."
        if roll < 0.65:
            return "say", {"message": self.rng.choice(self.GREETINGS)}, ""
        return self._wander(sim, agent)
