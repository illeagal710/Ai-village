"""Every action an agent can take, as a tool schema plus the code that applies it.

The schemas are given to Claude as tools. The same functions are used by the
offline brain, so both kinds of agent live under the same physics.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .agent import HEARING_RANGE, MAX_NOTES, Agent
from .world import BLOCK_MATERIALS, FOREST, GRASS, ITEMS, MAX_HEIGHT, ROCK, STRUCTURES, WATER, Structure

if TYPE_CHECKING:
    from .sim import Simulation

MOVE_STEPS = 4
BLOCK_REACH = 2
BLOCKS_PER_TURN = 8
COSTS = {"move_step": 0.5, "gather": 2.0, "build": 4.0, "demolish": 3.0}
BERRY_FULLNESS = 12


def _xy(props: dict | None = None) -> dict:
    p = {"x": {"type": "integer"}, "y": {"type": "integer"}}
    p.update(props or {})
    return p


def _tool(name: str, description: str, props: dict | None = None, required: list | None = None) -> dict:
    return {
        "name": name,
        "description": description,
        "input_schema": {"type": "object", "properties": props or {}, "required": required or []},
    }


_ITEM = {"type": "string", "enum": list(ITEMS)}
_AMOUNT = {"type": "integer", "minimum": 1}

TOOLS = [
    _tool("move_to", f"Walk toward a tile, up to {MOVE_STEPS} steps this turn (more along paths). You cannot walk on water (unless bridged) or through walls.",
          _xy(), ["x", "y"]),
    _tool("gather", "Take resources from a tile you are on or next to: wood from forest, stone from rock, berries from bushes or farms.",
          _xy(), ["x", "y"]),
    _tool("eat", f"Eat berries you carry. Each berry restores {BERRY_FULLNESS} fullness.",
          {"amount": _AMOUNT}, ["amount"]),
    _tool("build", "Build a structure on a tile you are on or next to, paying its cost from what you carry. "
          "For kind 'other', you invent the thing: give it a name and description and choose the materials to put into it.",
          _xy({
              "kind": {"type": "string", "enum": list(STRUCTURES)},
              "name": {"type": "string", "description": "Optional name for what you build."},
              "description": {"type": "string", "description": "Optional description others will see."},
              "text": {"type": "string", "description": "For signs: what the sign says."},
              "materials": {"type": "object", "description": "For kind 'other': items to use, e.g. {\"wood\": 3}.",
                            "additionalProperties": {"type": "integer"}},
          }), ["kind", "x", "y"]),
    _tool("place_blocks", f"Place up to {BLOCKS_PER_TURN} single blocks of wood or stone this turn, each using one wood or stone you carry. "
          "Blocks stack and form any shape: towers, walls, roofs, arches, sculptures. "
          f"z is the height layer: z=1 sits on the ground, z=2 on top of that, up to z={MAX_HEIGHT}. "
          "A block must rest on the ground, on a block below it, or touch a block beside it at the same height; blocks are placed in the order given. "
          f"You can reach columns up to {BLOCK_REACH} tiles away. A block at z=1 blocks walking; blocks higher up can be walked under.",
          {"blocks": {"type": "array", "minItems": 1, "maxItems": BLOCKS_PER_TURN, "items": {
              "type": "object", "required": ["x", "y", "z", "material"],
              "properties": {"x": {"type": "integer"}, "y": {"type": "integer"},
                             "z": {"type": "integer", "minimum": 1, "maximum": MAX_HEIGHT},
                             "material": {"type": "string", "enum": list(BLOCK_MATERIALS)}}}}},
          ["blocks"]),
    _tool("remove_block", f"Take away a single block within {BLOCK_REACH} tiles and get its material back.",
          {"x": {"type": "integer"}, "y": {"type": "integer"}, "z": {"type": "integer"}}, ["x", "y", "z"]),
    _tool("demolish", "Tear down a structure on a tile you are on or next to. You get back about half its materials.",
          _xy(), ["x", "y"]),
    _tool("write", "Write new text on a sign you are on or next to, replacing what it said.",
          _xy({"text": {"type": "string"}}), ["x", "y", "text"]),
    _tool("say", f"Say something out loud. Every being within {HEARING_RANGE} tiles hears it.",
          {"message": {"type": "string"}}, ["message"]),
    _tool("give", "Give items to a being next to you. Name them by name or by their number.",
          {"to": {"type": "string"}, "item": _ITEM, "amount": _AMOUNT}, ["to", "item", "amount"]),
    _tool("store", "Put items into a chest you are on or next to.",
          _xy({"item": _ITEM, "amount": _AMOUNT}), ["x", "y", "item", "amount"]),
    _tool("take", "Take items out of a chest you are on or next to.",
          _xy({"item": _ITEM, "amount": _AMOUNT}), ["x", "y", "item", "amount"]),
    _tool("rest", "Rest and recover energy. Faster inside a house or near a campfire."),
    _tool("remember", f"Write a private note to yourself. You keep up to {MAX_NOTES} notes; the oldest is dropped when full.",
          {"note": {"type": "string"}}, ["note"]),
    _tool("forget", "Erase one of your notes by its number.", {"number": {"type": "integer"}}, ["number"]),
    _tool("set_name", "Choose or change the name others know you by.", {"name": {"type": "string"}}, ["name"]),
]

TOOL_NAMES = {t["name"] for t in TOOLS}


class ActionError(Exception):
    pass


def _reach(agent: Agent, args: dict) -> tuple[int, int]:
    try:
        x, y = int(args["x"]), int(args["y"])
    except (KeyError, TypeError, ValueError):
        raise ActionError("you need to give x and y as whole numbers")
    if max(abs(x - agent.x), abs(y - agent.y)) > 1:
        raise ActionError(f"({x}, {y}) is out of reach; you can only act on your own tile or the 8 around it")
    return x, y


def _amount(args: dict) -> int:
    try:
        n = int(args.get("amount", 1))
    except (TypeError, ValueError):
        raise ActionError("amount must be a whole number")
    if n < 1:
        raise ActionError("amount must be at least 1")
    return n


def _item(args: dict) -> str:
    item = args.get("item")
    if item not in ITEMS:
        raise ActionError(f"unknown item {item!r}; items are {', '.join(ITEMS)}")
    return item


def _clip(text, n: int) -> str:
    return str(text or "").strip()[:n]


def apply(sim: "Simulation", agent: Agent, name: str, args: dict) -> str:
    """Apply an action and return a short result in the second person."""
    if name not in TOOL_NAMES:
        raise ActionError(f"there is no action called {name!r}")
    return globals()[f"_do_{name}"](sim, agent, args or {})


def _do_move_to(sim, agent, args):
    try:
        goal = (int(args["x"]), int(args["y"]))
    except (KeyError, TypeError, ValueError):
        raise ActionError("you need to give x and y as whole numbers")
    w = sim.world
    if not w.in_bounds(*goal):
        raise ActionError(f"({goal[0]}, {goal[1]}) is outside the world")
    occupied = {a.pos for a in sim.agents if a is not agent}
    route = w.path(agent.pos, goal, occupied)
    if not route:
        if agent.pos == goal:
            return "you are already there"
        raise ActionError(f"you can't find a way to ({goal[0]}, {goal[1]})")
    budget = float(MOVE_STEPS)
    moved = 0
    for x, y in route:
        s = w.tile(x, y).structure
        cost = 0.5 if s and s.kind in ("path", "bridge") else 1.0
        if budget < cost or (x, y) in occupied:
            break
        budget -= cost
        agent.x, agent.y = x, y
        moved += 1
    agent.energy -= COSTS["move_step"] * moved
    where = "and arrived" if agent.pos == goal or len(route) == moved else "and are on your way"
    return f"you walked {moved} step{'s' if moved != 1 else ''} to ({agent.x}, {agent.y}) {where}"


def _do_gather(sim, agent, args):
    x, y = _reach(agent, args)
    t = sim.world.tile(x, y)
    if agent.carried() >= 30:
        raise ActionError("your hands are full")
    rng = sim.world.rng
    if t.berries:
        n = agent.add("berries", min(t.berries, 2))
        t.berries -= n
        item = "berries"
    elif t.terrain == FOREST and t.wood:
        n = agent.add("wood", min(t.wood, rng.randint(1, 2)))
        t.wood -= n
        item = "wood"
        if not t.wood:
            t.terrain = GRASS   # the forest tile is cleared; it may come back as grass
    elif t.terrain == ROCK and t.stone:
        n = agent.add("stone", min(t.stone, rng.randint(1, 2)))
        t.stone -= n
        item = "stone"
        if not t.stone:
            t.terrain = GRASS
    else:
        raise ActionError(f"there is nothing to gather at ({x}, {y})")
    agent.energy -= COSTS["gather"]
    return f"you gathered {n} {item} at ({x}, {y})"


def _do_eat(sim, agent, args):
    n = min(_amount(args), agent.inventory.get("berries", 0))
    if not n:
        raise ActionError("you have no berries")
    needed = max(1, int((100 - agent.satiety) // BERRY_FULLNESS) + 1)
    n = min(n, needed)
    agent.remove("berries", n)
    agent.satiety = min(100.0, agent.satiety + n * BERRY_FULLNESS)
    return f"you ate {n} berr{'ies' if n != 1 else 'y'}; fullness is now {agent.satiety:.0f}"


def _do_build(sim, agent, args):
    x, y = _reach(agent, args)
    kind = args.get("kind")
    if kind not in STRUCTURES:
        raise ActionError(f"unknown kind {kind!r}")
    w = sim.world
    t = w.tile(x, y)
    if t.structure:
        raise ActionError(f"there is already {t.structure.label()} at ({x}, {y})")
    if kind == "bridge" and t.terrain != WATER:
        raise ActionError("bridges can only be built on water")
    if kind != "bridge" and t.terrain == WATER:
        raise ActionError("only bridges can be built on water")
    if kind == "farm" and t.terrain != GRASS:
        raise ActionError("farms need grass")
    if (x, y, 1) in w.blocks:
        raise ActionError(f"there are blocks in the way at ({x}, {y})")
    if STRUCTURES[kind].get("blocks") and any(a.pos == (x, y) for a in sim.agents):
        raise ActionError("someone is standing there")

    if kind == "other":
        raw = args.get("materials") or {}
        if not isinstance(raw, dict):
            raise ActionError("materials must be like {\"wood\": 2}")
        cost = {}
        for item, n in raw.items():
            if item not in ITEMS:
                raise ActionError(f"unknown material {item!r}")
            if int(n) > 0:
                cost[item] = int(n)
        if not cost:
            raise ActionError("something new still needs at least one material")
        if not _clip(args.get("name"), 1):
            raise ActionError("give what you build a name")
    else:
        cost = dict(STRUCTURES[kind]["cost"])

    missing = [f"{n - agent.inventory.get(i, 0)} more {i}" for i, n in cost.items() if agent.inventory.get(i, 0) < n]
    if missing:
        raise ActionError(f"a {kind} needs {', '.join(missing)}")
    for item, n in cost.items():
        agent.remove(item, n)

    t.structure = Structure(
        kind=kind, x=x, y=y, builder=agent.label, built_tick=w.tick,
        name=_clip(args.get("name"), 40), description=_clip(args.get("description"), 200),
        text=_clip(args.get("text"), 300) if kind == "sign" else "", materials=cost,
    )
    if kind == "farm":
        t.berries = min(t.berries, 8)
    agent.energy -= COSTS["build"]
    return f"you built {t.structure.label()} at ({x}, {y})"


def _block_xyz(agent: Agent, args: dict) -> tuple[int, int, int]:
    try:
        x, y, z = int(args["x"]), int(args["y"]), int(args["z"])
    except (KeyError, TypeError, ValueError):
        raise ActionError("you need to give x, y and z as whole numbers")
    if max(abs(x - agent.x), abs(y - agent.y)) > BLOCK_REACH:
        raise ActionError(f"({x}, {y}) is out of reach; blocks can be placed up to {BLOCK_REACH} tiles away")
    if not 1 <= z <= MAX_HEIGHT:
        raise ActionError(f"z must be between 1 and {MAX_HEIGHT}")
    return x, y, z


def _do_place_blocks(sim, agent, args):
    wanted = args.get("blocks")
    if isinstance(wanted, dict):
        wanted = [wanted]
    if not isinstance(wanted, list) or not wanted:
        raise ActionError("give a list of blocks, each with x, y, z and material")
    placed, problem = [], ""
    for b in wanted[:BLOCKS_PER_TURN]:
        try:
            placed.append(_place_one(sim, agent, b if isinstance(b, dict) else {}))
        except ActionError as exc:
            problem = str(exc)
            break
    if not placed:
        raise ActionError(problem)
    agent.energy -= 0.5 * len(placed)
    where = "; ".join(placed)
    tail = f"; then stopped because {problem}" if problem else ""
    return f"you placed {len(placed)} block{'s' if len(placed) != 1 else ''}: {where}{tail}"


def _place_one(sim, agent, args) -> str:
    x, y, z = _block_xyz(agent, args)
    w = sim.world
    if not w.in_bounds(x, y):
        raise ActionError("that is outside the world")
    material = args.get("material")
    if material not in BLOCK_MATERIALS:
        raise ActionError(f"blocks can be made of {' or '.join(BLOCK_MATERIALS)}")
    if (x, y, z) in w.blocks:
        raise ActionError(f"there is already a {w.blocks[(x, y, z)]} block at ({x}, {y}, z={z})")
    s = w.tile(x, y).structure
    if s and s.kind != "path":
        raise ActionError(f"{s.label()} stands at ({x}, {y})")
    if z == 1 and any(a.pos == (x, y) for a in sim.agents):
        raise ActionError("someone is standing there")
    if not w.supported(x, y, z):
        raise ActionError(f"a block at z={z} would float; it needs a block under it or beside it")
    if not agent.remove(material, 1):
        raise ActionError(f"you have no {material}")
    w.blocks[(x, y, z)] = material
    return f"{material} at ({x}, {y}, z={z})"


def _do_remove_block(sim, agent, args):
    x, y, z = _block_xyz(agent, args)
    w = sim.world
    material = w.blocks.get((x, y, z))
    if not material:
        raise ActionError(f"there is no block at ({x}, {y}, z={z})")
    if not agent.add(material, 1):
        raise ActionError("your hands are full")
    del w.blocks[(x, y, z)]
    agent.energy -= 1.0
    return f"you removed the {material} block at ({x}, {y}, z={z})"


def _do_demolish(sim, agent, args):
    x, y = _reach(agent, args)
    t = sim.world.tile(x, y)
    s = t.structure
    if not s:
        raise ActionError(f"there is no structure at ({x}, {y})")
    refund = []
    for item, n in {**s.materials}.items():
        got = agent.add(item, n // 2)
        if got:
            refund.append(f"{got} {item}")
    for item, n in s.storage.items():
        got = agent.add(item, n)
        if got:
            refund.append(f"{got} {item} from inside")
    t.structure = None
    agent.energy -= COSTS["demolish"]
    back = f" and got back {', '.join(refund)}" if refund else ""
    return f"you tore down {s.label()} built by {s.builder} at ({x}, {y}){back}"


def _do_write(sim, agent, args):
    x, y = _reach(agent, args)
    s = sim.world.tile(x, y).structure
    if not s or s.kind != "sign":
        raise ActionError(f"there is no sign at ({x}, {y})")
    s.text = _clip(args.get("text"), 300)
    return f'you wrote on the sign at ({x}, {y}): "{s.text}"'


def _do_say(sim, agent, args):
    msg = _clip(args.get("message"), 400)
    if not msg:
        raise ActionError("you said nothing")
    heard = 0
    for other in sim.agents:
        if other is agent:
            continue
        d = max(abs(other.x - agent.x), abs(other.y - agent.y))
        if d <= HEARING_RANGE:
            other.inbox.append(f'{agent.label} [{agent.symbol}] at ({agent.x}, {agent.y}), {d} tiles away, said: "{msg}"')
            heard += 1
    sim.world.log(agent.label, msg, kind="speech")
    who = f"{heard} being{'s' if heard != 1 else ''} could hear you" if heard else "nobody was close enough to hear"
    return f'you said "{msg}" ({who})'


def _find_being(sim, agent, ref) -> Agent:
    ref = str(ref or "").strip().lstrip("[#").rstrip("]")
    for a in sim.agents:
        if a is agent:
            continue
        if ref.lower() in (str(a.id), a.symbol, a.label.lower(), (a.name or "").lower()):
            return a
    raise ActionError(f"you don't see anyone called {ref!r}")


def _do_give(sim, agent, args):
    other = _find_being(sim, agent, args.get("to"))
    if max(abs(other.x - agent.x), abs(other.y - agent.y)) > 1:
        raise ActionError(f"{other.label} is not next to you")
    item, n = _item(args), _amount(args)
    if agent.inventory.get(item, 0) < n:
        raise ActionError(f"you don't have {n} {item}")
    got = other.add(item, n)
    if not got:
        raise ActionError(f"{other.label} can't carry any more")
    agent.remove(item, got)
    other.remember_event(sim.world.tick, f"{agent.label} gave you {got} {item}.")
    return f"you gave {got} {item} to {other.label}"


def _chest(sim, agent, args) -> Structure:
    x, y = _reach(agent, args)
    s = sim.world.tile(x, y).structure
    if not s or s.kind != "chest":
        raise ActionError(f"there is no chest at ({x}, {y})")
    return s


def _do_store(sim, agent, args):
    chest, item, n = _chest(sim, agent, args), _item(args), _amount(args)
    if not agent.remove(item, n):
        raise ActionError(f"you don't have {n} {item}")
    chest.storage[item] = chest.storage.get(item, 0) + n
    return f"you put {n} {item} into the chest at ({chest.x}, {chest.y})"


def _do_take(sim, agent, args):
    chest, item, n = _chest(sim, agent, args), _item(args), _amount(args)
    n = min(n, chest.storage.get(item, 0))
    if not n:
        raise ActionError(f"the chest has no {item}")
    got = agent.add(item, n)
    if not got:
        raise ActionError("your hands are full")
    chest.storage[item] -= got
    return f"you took {got} {item} from the chest at ({chest.x}, {chest.y})"


def rest_gain(sim, agent) -> tuple[float, str]:
    w = sim.world
    here = w.tile(agent.x, agent.y).structure
    if here and here.kind == "house":
        return 18.0, f"inside {here.label()}"
    for x in range(agent.x - 2, agent.x + 3):
        for y in range(agent.y - 2, agent.y + 3):
            if w.in_bounds(x, y) and (s := w.tile(x, y).structure) and s.kind == "campfire":
                return 10.0, "by the campfire"
    return 6.0, "in the open"


def _do_rest(sim, agent, args):
    gain, where = rest_gain(sim, agent)
    agent.energy = min(100.0, agent.energy + gain)
    return f"you rested {where}; energy is now {agent.energy:.0f}"


def _do_remember(sim, agent, args):
    note = _clip(args.get("note"), 300)
    if not note:
        raise ActionError("the note is empty")
    agent.notes.append(note)
    del agent.notes[:-MAX_NOTES]
    return "you made a note"


def _do_forget(sim, agent, args):
    try:
        i = int(args.get("number")) - 1
        agent.notes.pop(i)
    except (TypeError, ValueError, IndexError):
        raise ActionError("there is no note with that number")
    return "you erased the note"


def _do_set_name(sim, agent, args):
    name = _clip(args.get("name"), 24)
    if not name:
        raise ActionError("a name can't be empty")
    if name.isdigit():
        raise ActionError("a name can't be only digits")
    if any(a is not agent and (a.name or "").lower() == name.lower() for a in sim.agents):
        raise ActionError(f"someone is already called {name}")
    old = agent.label
    agent.name = name
    return f"you are now called {name} (before: {old})"
