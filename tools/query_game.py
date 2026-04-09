#!/usr/bin/env python3
"""Query game logs from the CLI.

Loads JSONL game logs dumped by GameRecorder and evaluates Python
expressions against them. Designed for LLM agents to run after a
match to analyze what happened.

Usage:
    # Print summary of a game
    python tools/query_game.py /tmp/coglet_learnings/game_123_a0.jsonl summary

    # Evaluate arbitrary Python against the records
    python tools/query_game.py /tmp/coglet_learnings/game_123_a0.jsonl eval "len([r for r in records if r['hp'] == 0])"
    python tools/query_game.py /tmp/coglet_learnings/game_123_a0.jsonl eval "[(r['step'], r['team_resources']['carbon']) for r in records[::100]]"

    # Load junction events alongside
    python tools/query_game.py /tmp/coglet_learnings/game_123_a0.jsonl --events game_123_a0_events.jsonl eval "len(events)"

    # Print the last N records as JSON
    python tools/query_game.py /tmp/coglet_learnings/game_123_a0.jsonl tail 10

    # Filter records matching a condition
    python tools/query_game.py /tmp/coglet_learnings/game_123_a0.jsonl filter "r['hp'] < 20"
"""

import argparse
import json
import sys
from pathlib import Path


def load_jsonl(path: str) -> list[dict]:
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def cmd_summary(records: list[dict], events: list[dict]) -> None:
    if not records:
        print("No records.")
        return
    first, last = records[0], records[-1]
    steps = last["step"] - first["step"]

    # Deaths
    deaths = 0
    prev_hp = None
    for r in records:
        if prev_hp is not None and prev_hp > 0 and r["hp"] == 0:
            deaths += 1
        prev_hp = r["hp"]

    # Unique positions
    positions = {tuple(r["position"]) for r in records}

    # Junction summary from last record
    junctions = last.get("junction_owners", {})
    owners = list(junctions.values())

    # Resource delta
    first_res = first.get("team_resources", {})
    last_res = last.get("team_resources", {})

    print(f"Steps: {first['step']} → {last['step']} ({steps} steps, {len(records)} records)")
    print(f"Final HP: {last['hp']}")
    print(f"Deaths: {deaths}")
    print(f"Positions visited: {len(positions)}")
    print(f"Known junctions: {len(junctions)}")
    if owners:
        unique_owners = set(owners)
        for owner in sorted(unique_owners, key=lambda o: o or ""):
            count = owners.count(owner)
            label = owner if owner else "neutral"
            print(f"  {label}: {count}")
    print(f"Junction events: {len(events)}")
    print("Resource delta:")
    for elem in ("carbon", "oxygen", "germanium", "silicon"):
        delta = last_res.get(elem, 0) - first_res.get(elem, 0)
        print(f"  {elem}: {first_res.get(elem, 0)} → {last_res.get(elem, 0)} ({delta:+d})")


def cmd_tail(records: list[dict], n: int) -> None:
    for r in records[-n:]:
        print(json.dumps(r))


def cmd_filter(records: list[dict], expr: str) -> None:
    results = [r for r in records if eval(expr, {"r": r})]  # noqa: S307
    for r in results:
        print(json.dumps(r))
    print(f"--- {len(results)}/{len(records)} records matched", file=sys.stderr)


def cmd_eval(records: list[dict], events: list[dict], expr: str) -> None:
    result = eval(expr, {"records": records, "events": events, "len": len, "sum": sum, "min": min, "max": max, "sorted": sorted, "set": set, "enumerate": enumerate, "zip": zip, "abs": abs, "round": round})  # noqa: S307
    if isinstance(result, (list, dict)):
        print(json.dumps(result, indent=2, default=str))
    else:
        print(result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Query game logs from GameRecorder dumps.")
    parser.add_argument("log", help="Path to JSONL game log")
    parser.add_argument("--events", help="Path to JSONL junction events file")
    parser.add_argument("command", choices=["summary", "tail", "filter", "eval"], help="Query command")
    parser.add_argument("arg", nargs="?", default=None, help="Command argument (N for tail, expression for filter/eval)")
    args = parser.parse_args()

    records = load_jsonl(args.log)

    events: list[dict] = []
    events_path = args.events
    if events_path is None:
        # Auto-detect events file alongside the log
        log_path = Path(args.log)
        candidate = log_path.parent / log_path.name.replace(".jsonl", "_events.jsonl")
        if candidate.exists():
            events_path = str(candidate)
    if events_path:
        events = load_jsonl(events_path)

    if args.command == "summary":
        cmd_summary(records, events)
    elif args.command == "tail":
        n = int(args.arg) if args.arg else 5
        cmd_tail(records, n)
    elif args.command == "filter":
        if not args.arg:
            parser.error("filter requires an expression")
        cmd_filter(records, args.arg)
    elif args.command == "eval":
        if not args.arg:
            parser.error("eval requires an expression")
        cmd_eval(records, events, args.arg)


if __name__ == "__main__":
    main()
