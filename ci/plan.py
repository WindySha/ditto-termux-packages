#!/usr/bin/env python3
"""Plan a build round: the recipes not in the repository yet whose dependencies are.

A recipe whose missing dependencies all sit in one job is queued in that job after them, so
chains build in one round. Recipes in scripts/big-pkgs.list, or that ran out of time in a
shared job, get a workflow run of their own.

Writes to $GITHUB_OUTPUT:
  matrix   {"include": [{"chunk": n, "packages": "a b@a", "budget": minutes}]}, where b@a
           means b is skipped if a didn't build
  count    number of jobs in matrix
  singles  JSON list of recipes to dispatch on their own
"""
import argparse
import json
import os
import sys
import time

MAX_ATTEMPTS = 2
INFLIGHT_SECONDS = 8 * 3600
ROUND_BUDGET_MINUTES = 210


def index_names(path):
    with open(path, encoding="utf-8") as f:
        return {line[9:].strip() for line in f if line.startswith("Package: ")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--termux-packages", required=True)
    parser.add_argument("--index", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--targets", required=True)
    parser.add_argument("--jobs", type=int, default=20)
    parser.add_argument("--per-job", type=int, default=30)
    parser.add_argument("--output", default=os.environ.get("GITHUB_OUTPUT", "/dev/stdout"))
    args = parser.parse_args()

    with open(args.targets, encoding="utf-8") as f:
        targets = [line.strip() for line in f if line.strip()]
    index = index_names(args.index)
    state = {}
    if os.path.exists(args.state):
        with open(args.state, encoding="utf-8") as f:
            state = json.load(f)
    failed = state.get("failed", {})
    built = set(state.get("built", []))
    now = time.time()
    inflight = {n for n, t in state.get("inflight", {}).items() if now - t < INFLIGHT_SECONDS}

    tp = os.path.abspath(args.termux_packages)
    sys.path.insert(0, os.path.join(tp, "scripts"))
    os.chdir(tp)
    import buildorder

    buildorder.termux_arch = "aarch64"
    buildorder.termux_pkg_library = "bionic"
    buildorder.termux_global_library = "false"
    pkgs_map = buildorder.read_packages_from_directories(
        ["packages", "root-packages", "x11-packages"], False, False)
    recipes = {p.name: p for p in pkgs_map.values() if isinstance(p, buildorder.TermuxPackage)}
    with open("scripts/big-pkgs.list", encoding="utf-8") as f:
        big = {line.strip() for line in f if line.strip()}

    deps = {}
    for name, recipe in recipes.items():
        names = set(recipe.deps)
        for sub in recipe.subpkgs:
            names |= sub.deps
        names -= recipe.antideps
        deps[name] = {pkgs_map[n].name for n in names if n in pkgs_map} - {name}

    def done(name):
        return name in index or name in built

    needed = set()
    stack = [t for t in targets if t in recipes]
    while stack:
        name = stack.pop()
        if name in needed or done(name):
            continue
        needed.add(name)
        stack.extend(deps[name])

    blocked = {n for n in needed if failed.get(n, {}).get("attempts", 0) >= MAX_ATTEMPTS}
    while True:
        more = {n for n in needed - blocked if deps[n] & blocked}
        if not more:
            break
        blocked |= more
    pending = sorted(needed - blocked - inflight)
    ready = [n for n in pending if all(done(d) for d in deps[n])]
    if not ready and not inflight and pending:
        # A dependency cycle: start with the recipes missing the fewest dependencies and let
        # build-package.sh build those inline.
        ready = sorted(pending, key=lambda n: (sum(not done(d) for d in deps[n]), n))[:args.jobs]

    singles = [n for n in ready if n in big or failed.get(n, {}).get("status") == "timeout"]
    shared = [n for n in ready if n not in singles][:args.jobs * args.per_job]
    chunk_count = min(args.jobs, len(shared))
    chunks = [shared[i::chunk_count] for i in range(chunk_count)]
    chunk_of = {n: i for i, chunk in enumerate(chunks) for n in chunk}
    waits = {}
    queued = True
    while queued:
        queued = False
        for name in pending:
            if name in chunk_of or name in big or failed.get(name, {}).get("status") == "timeout":
                continue
            missing = {d for d in deps[name] if not done(d)}
            homes = {chunk_of.get(d) for d in missing}
            if missing and None not in homes and len(homes) == 1:
                home = homes.pop()
                if len(chunks[home]) < args.per_job * 2:
                    chunks[home].append(name)
                    chunk_of[name] = home
                    waits[name] = sorted(missing)
                    queued = True

    matrix = [{
        "chunk": i + 1,
        "packages": " ".join(n + ("@" + ",".join(waits[n]) if n in waits else "") for n in chunk),
        "budget": ROUND_BUDGET_MINUTES,
    } for i, chunk in enumerate(chunks)]

    target_set = set(targets) & set(recipes)
    print(f"targets built: {sum(done(t) for t in target_set)}/{len(target_set)}")
    print(f"still needed: {len(needed)}, building elsewhere: {len(inflight & needed)}")
    print(f"this round: {len(chunk_of)} in {len(chunks)} jobs, {len(singles)} on their own")
    if blocked:
        print(f"given up ({len(blocked)}):")
        for name in sorted(blocked):
            reason = failed.get(name, {}).get("status") or "needs " + ", ".join(
                sorted(deps[name] & blocked))
            print(f"  {name}: {reason}")
    with open(args.output, "a", encoding="utf-8") as f:
        f.write(f"matrix={json.dumps({'include': matrix})}\n")
        f.write(f"count={len(matrix)}\n")
        f.write(f"singles={json.dumps(singles)}\n")


if __name__ == "__main__":
    main()
