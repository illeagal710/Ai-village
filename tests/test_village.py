import json

from village import actions
from village.agent import Agent, perceive
from village.brains import OfflineBrain
from village.server import History
from village.sim import Simulation
from village.world import FOREST, GRASS, ROCK, WATER, World


def make_sim(tmp_path=None, seed=1, agents=4):
    return Simulation.new(OfflineBrain(seed), n_agents=agents, seed=seed, run_dir=tmp_path)


def flat_sim():
    """A tiny all-grass world with one agent at (2, 2)."""
    sim = make_sim(agents=1)
    w = World(8, 8, seed=0)
    for row in w.tiles:
        for t in row:
            t.terrain, t.wood, t.stone, t.berries, t.structure = GRASS, 0, 0, 0, None
    sim.world = w
    sim.agents[0].x, sim.agents[0].y = 2, 2
    return sim, sim.agents[0]


def test_world_generation_is_deterministic():
    a, b = World(30, 20, seed=42), World(30, 20, seed=42)
    assert [[t.terrain for t in r] for r in a.tiles] == [[t.terrain for t in r] for r in b.tiles]
    kinds = {t.terrain for r in a.tiles for t in r}
    assert GRASS in kinds


def test_gather_build_and_rest_in_house():
    sim, a = flat_sim()
    sim.world.tile(3, 2).terrain, sim.world.tile(3, 2).wood = FOREST, 6
    sim.world.tile(1, 2).terrain, sim.world.tile(1, 2).stone = ROCK, 12
    for _ in range(10):
        try:
            actions.apply(sim, a, "gather", {"x": 3, "y": 2})
        except actions.ActionError:
            break
    for _ in range(6):
        actions.apply(sim, a, "gather", {"x": 1, "y": 2})
    a.inventory = {"wood": 8, "stone": 4}
    with __import__("pytest").raises(actions.ActionError):
        actions.apply(sim, a, "build", {"kind": "house", "x": 5, "y": 5})   # out of reach
    actions.apply(sim, a, "build", {"kind": "house", "x": 2, "y": 3, "name": "Home"})
    assert sim.world.tile(2, 3).structure.name == "Home"
    assert a.inventory == {}
    actions.apply(sim, a, "move_to", {"x": 2, "y": 3})
    a.energy = 10
    actions.apply(sim, a, "rest", {})
    assert a.energy == 28


def test_build_other_needs_name_and_materials():
    sim, a = flat_sim()
    a.inventory = {"stone": 3}
    with __import__("pytest").raises(actions.ActionError):
        actions.apply(sim, a, "build", {"kind": "other", "x": 2, "y": 3, "materials": {"stone": 3}})
    msg = actions.apply(sim, a, "build", {"kind": "other", "x": 2, "y": 3, "name": "Tower of Dawn",
                                          "description": "Three stones stacked.", "materials": {"stone": 3}})
    assert "Tower of Dawn" in msg
    actions.apply(sim, a, "demolish", {"x": 2, "y": 3})
    assert a.inventory == {"stone": 1}


def test_walls_block_and_bridges_cross():
    sim, a = flat_sim()
    w = sim.world
    for y in range(8):
        w.tile(4, y).terrain = WATER
    try:
        actions.apply(sim, a, "move_to", {"x": 6, "y": 2})
        assert False, "should not cross water"
    except actions.ActionError:
        pass
    a.inventory = {"wood": 4}
    a.x = 3
    actions.apply(sim, a, "build", {"kind": "bridge", "x": 4, "y": 2})
    actions.apply(sim, a, "move_to", {"x": 6, "y": 2})
    assert a.pos == (6, 2)


def test_speech_reaches_nearby_beings_only():
    sim = make_sim(agents=3)
    a, b, c = sim.agents
    a.x, a.y, b.x, b.y, c.x, c.y = 0, 0, 5, 0, 30, 20
    actions.apply(sim, a, "say", {"message": "hi"})
    assert b.inbox and not c.inbox
    assert "hi" in perceive(sim, b)


def test_names_are_unique():
    sim = make_sim(agents=2)
    actions.apply(sim, sim.agents[0], "set_name", {"name": "Wren"})
    try:
        actions.apply(sim, sim.agents[1], "set_name", {"name": "wren"})
        assert False
    except actions.ActionError:
        pass


def test_offline_run_records_history_and_resumes(tmp_path):
    sim = make_sim(tmp_path)
    for _ in range(60):
        sim.step()
    assert sim.world.tick == 60
    h = History(tmp_path / "history.jsonl")
    assert h.refresh() == 60
    last = json.loads(h.get(-1))
    assert last["tick"] == 60 and len(last["agents"]) == 4
    sim.save(tmp_path / "world.json")
    again = Simulation.load(tmp_path / "world.json", OfflineBrain(2), tmp_path)
    assert again.world.tick == 60
    assert [a.pos for a in again.agents] == [a.pos for a in sim.agents]
    again.step()
    assert h.refresh() == 61


def test_perception_has_no_goals():
    sim = make_sim(agents=2)
    text = perceive(sim, sim.agents[0]).lower()
    for word in ("goal", "task", "should", "objective"):
        assert word not in text


def test_export_writes_a_standalone_page(tmp_path):
    from village.__main__ import main
    sim = make_sim(tmp_path)
    for _ in range(5):
        sim.step()
    out = tmp_path / "v.html"
    main(["export", str(tmp_path), "-o", str(out)])
    page = out.read_text()
    assert "window.VILLAGE_FRAMES=[" in page and "Village3D" in page
    assert 'src="vendor/' not in page and "cdn.jsdelivr.net/npm/three@0.147.0" in page


def test_blocks_stack_need_support_and_block_walking():
    sim, a = flat_sim()
    a.inventory = {"stone": 6, "wood": 2}
    msg = actions.apply(sim, a, "place_blocks", {"blocks": [
        {"x": 3, "y": 2, "z": 1, "material": "stone"},
        {"x": 3, "y": 2, "z": 2, "material": "stone"},
        {"x": 4, "y": 2, "z": 2, "material": "wood"},     # overhang, held by its neighbour
        {"x": 4, "y": 4, "z": 3, "material": "stone"},    # floats: stops here
        {"x": 1, "y": 1, "z": 1, "material": "stone"},
    ]})
    assert "3 blocks" in msg and "float" in msg
    assert sim.world.blocks[(4, 2, 2)] == "wood"
    assert not sim.world.passable(3, 2) and sim.world.passable(4, 2)   # walk under the overhang
    assert "z1-2 stone" in perceive(sim, a)
    actions.apply(sim, a, "remove_block", {"x": 4, "y": 2, "z": 2})
    assert a.inventory["wood"] == 2
