"""Command line entry point.

  python -m village run       start a new world (or --resume an old one) and watch it live
  python -m village replay    scrub through the history of a past run
  python -m village export    save a run as one HTML file you can open or share anywhere
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path

from .brains import DEFAULT_MODEL, ClaudeBrain, OfflineBrain
from .server import History, serve
from .sim import Simulation

RUNS = Path("runs")


def make_brain(args):
    if args.offline:
        return OfflineBrain(args.seed), "offline brain"
    have_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    try:
        import anthropic  # noqa: F401
    except ImportError:
        have_key = None
    if not have_key:
        print("No ANTHROPIC_API_KEY found (or the anthropic package is missing), so the agents will use the "
              "simple offline brain.\nSet ANTHROPIC_API_KEY and `pip install anthropic` to let Claude drive them.\n")
        return OfflineBrain(args.seed), "offline brain"
    return ClaudeBrain(model=args.model, effort=args.effort, fallbacks=not args.no_fallbacks), f"Claude ({args.model})"


def cmd_run(args):
    brain, brain_name = make_brain(args)
    if args.resume:
        run_dir = Path(args.resume)
        sim = Simulation.load(run_dir / "world.json", brain, run_dir)
        print(f"Resumed {run_dir} at tick {sim.world.tick}.")
    else:
        run_dir = Path(args.run_dir) if args.run_dir else RUNS / datetime.now().strftime("%Y-%m-%d_%H%M%S")
        sim = Simulation.new(brain, n_agents=args.agents, width=args.width, height=args.height,
                             seed=args.seed, run_dir=run_dir)
        print(f"New world (seed {sim.world.seed}) with {len(sim.agents)} beings, driven by {brain_name}.")
    print(f"Recording to {run_dir}/")

    if not args.no_web:
        serve(History(run_dir / "history.jsonl"), port=args.port, sim=sim, host=args.host)
        url = f"http://localhost:{args.port}"
        print(f"Watch it at {url}  (Ctrl+C to stop; the world is saved and can be resumed)\n")
        if args.open:
            webbrowser.open(url)

    end = sim.world.tick + args.ticks if args.ticks else None
    try:
        while end is None or sim.world.tick < end:
            started = time.time()
            events = sim.step()
            if not args.quiet:
                for ev in events:
                    mark = " " if ev["ok"] else "x"
                    print(f"[{ev['tick']:>5}] {mark} {ev['who']}: {ev['result']}")
            time.sleep(max(0.0, args.delay - (time.time() - started)))
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        sim.save(run_dir / "world.json")
        print(f"Saved. Resume with: python -m village run --resume {run_dir}")
        print(f"Replay with:        python -m village replay {run_dir}")
    if not args.no_web and args.ticks:
        print("Simulation finished; the viewer stays up so you can replay. Ctrl+C to quit.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


def cmd_replay(args):
    run_dir = Path(args.run_dir) if args.run_dir else _latest_run()
    history = History(run_dir / "history.jsonl")
    n = history.refresh()
    if not n:
        sys.exit(f"No history found in {run_dir}")
    serve(history, port=args.port, host=args.host)
    url = f"http://localhost:{args.port}"
    print(f"Replaying {run_dir} ({n} turns) at {url}  (Ctrl+C to quit)")
    if args.open:
        webbrowser.open(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


def cmd_export(args):
    run_dir = Path(args.run_dir) if args.run_dir else _latest_run()
    history = run_dir / "history.jsonl"
    if not history.exists():
        sys.exit(f"No history found in {run_dir}")
    frames = history.read_text().splitlines()
    if args.every > 1:
        frames = frames[::args.every] + ([frames[-1]] if (len(frames) - 1) % args.every else [])
    data = "[" + ",".join(frames) + "]"
    page = (Path(__file__).parent / "static" / "index.html").read_text()
    inline = "<script>window.VILLAGE_FRAMES=" + data.replace("</", "<\\/") + ";</script>\n<script>"
    page = page.replace("<script>", inline, 1)
    out = Path(args.out) if args.out else run_dir / "village.html"
    out.write_text(page)
    print(f"Wrote {out} ({len(frames)} turns, {out.stat().st_size / 1e6:.1f} MB). Open it in any browser.")


def _latest_run() -> Path:
    runs = sorted(p for p in RUNS.glob("*") if (p / "history.jsonl").exists())
    if not runs:
        sys.exit("No runs found. Start one with: python -m village run")
    return runs[-1]


def main(argv=None):
    p = argparse.ArgumentParser(prog="village", description="A buildable world where AI beings do whatever they want.")
    sub = p.add_subparsers(dest="cmd")

    r = sub.add_parser("run", help="run a world and watch it live")
    r.add_argument("--agents", type=int, default=6, help="number of beings (default 6)")
    r.add_argument("--ticks", type=int, default=0, help="stop after this many turns (default: run until Ctrl+C)")
    r.add_argument("--width", type=int, default=48)
    r.add_argument("--height", type=int, default=32)
    r.add_argument("--seed", type=int, default=None, help="world seed, for a reproducible map")
    r.add_argument("--model", default=DEFAULT_MODEL, help=f"Claude model (default {DEFAULT_MODEL})")
    r.add_argument("--effort", default="low", choices=["low", "medium", "high", "xhigh", "max"],
                   help="how hard each being thinks per turn (default low)")
    r.add_argument("--no-fallbacks", action="store_true", help="turn off server-side refusal fallbacks")
    r.add_argument("--offline", action="store_true", help="use the simple offline brain (no API calls)")
    r.add_argument("--delay", type=float, default=0.5, help="minimum seconds per turn (default 0.5)")
    r.add_argument("--run-dir", help="where to record this run (default runs/<date_time>)")
    r.add_argument("--resume", help="resume a previous run directory")
    r.add_argument("--port", type=int, default=8000)
    r.add_argument("--host", default="127.0.0.1")
    r.add_argument("--no-web", action="store_true", help="don't start the viewer")
    r.add_argument("--open", action="store_true", help="open the viewer in your browser")
    r.add_argument("--quiet", action="store_true", help="don't print every action")
    r.set_defaults(func=cmd_run)

    rp = sub.add_parser("replay", help="replay a recorded run in the viewer")
    rp.add_argument("run_dir", nargs="?", help="run directory (default: the most recent run)")
    rp.add_argument("--port", type=int, default=8000)
    rp.add_argument("--host", default="127.0.0.1")
    rp.add_argument("--open", action="store_true")
    rp.set_defaults(func=cmd_replay)

    ex = sub.add_parser("export", help="save a recorded run as a single HTML file")
    ex.add_argument("run_dir", nargs="?", help="run directory (default: the most recent run)")
    ex.add_argument("-o", "--out", help="output file (default <run_dir>/village.html)")
    ex.add_argument("--every", type=int, default=1, help="keep every Nth turn to make the file smaller")
    ex.set_defaults(func=cmd_export)

    args = p.parse_args(argv)
    if not args.cmd:
        p.print_help()
        return
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    args.func(args)


if __name__ == "__main__":
    main()
