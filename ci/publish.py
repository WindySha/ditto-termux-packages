#!/usr/bin/env python3
"""Upload the packages build jobs made and merge them into the repository index.

New .deb files go to the releases pool-1, pool-2, ... (a release holds at most 1000 assets),
and the index in the stable release points at them with "Filename: pool-N/<name>.deb", which
apt resolves against the releases/download URL. The index goes up every few hundred packages,
so a publish cut short keeps what it uploaded.

Also records in the ci release's state.json which recipes failed, for the planner.

  ci/publish.py <artifacts dir> <work dir>

Each artifact holds debs.tar, results.tsv (from ci/build.sh) and logs/. Needs gh with GH_REPO
set, dpkg-deb and dpkg-scanpackages.
"""
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
from email.utils import formatdate
from pathlib import Path

REPO = os.environ["GH_REPO"]
POOL_CAPACITY = 990
UPLOAD_BATCH = 20
INDEX_EVERY = 200


def run(*cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout


def gh(*args, tries=8):
    delay = 30
    for attempt in range(tries):
        p = subprocess.run(["gh", *args], capture_output=True, text=True)
        if p.returncode == 0:
            return p.stdout
        print(f"gh {' '.join(args[:4])}: {p.stderr.strip()[-400:]}", file=sys.stderr)
        if "HTTP 404" in p.stderr or attempt + 1 == tries:
            raise RuntimeError(p.stderr)
        time.sleep(delay)
        delay = min(delay * 2, 900)


def releases():
    out = gh("api", "--paginate", f"repos/{REPO}/releases?per_page=100", "-q", ".[] | [.tag_name, .id] | @tsv")
    return dict(line.split("\t") for line in out.splitlines())


def assets(release_id):
    out = gh("api", "--paginate", f"repos/{REPO}/releases/{release_id}/assets?per_page=100",
             "-q", ".[] | [.name, .size, .id] | @tsv")
    rows = (line.split("\t") for line in out.splitlines())
    return {name: (int(size), asset_id) for name, size, asset_id in rows}


def download(tag, name, dest):
    for asset_name, (_, asset_id) in assets(releases()[tag]).items():
        if asset_name == name:
            gh("release", "download", tag, "-p", name, "-D", str(dest), "--clobber")
            return dest / name
    return None


def parse_index(text):
    stanzas = {}
    for block in text.strip().split("\n\n"):
        fields = dict(re.findall(r"^([\w-]+): (.*)$", block, re.M))
        if "Package" in fields:
            stanzas[fields["Package"]] = block.strip()
    return stanzas


def version_of(stanza):
    return re.search(r"^Version: (.*)$", stanza, re.M).group(1)


def asset_name(deb_name):
    return re.sub(r"[^A-Za-z0-9._-]", "_", re.sub(r"_[0-9]+:", "_", deb_name, count=1))


def write_index(stanzas, dist):
    dist.mkdir(parents=True, exist_ok=True)
    packages = "\n\n".join(stanzas[name] for name in sorted(stanzas)) + "\n"
    (dist / "Packages").write_text(packages, encoding="utf-8")
    (dist / "Packages.gz").write_bytes(gzip.compress(packages.encode(), 9, mtime=0))
    lines = [
        "Origin: Ditto",
        "Label: Ditto Termux packages",
        "Suite: stable",
        "Codename: stable",
        "Architectures: aarch64 all",
        f"Date: {formatdate(usegmt=True)}",
        "SHA256:",
    ]
    for name in ("Packages", "Packages.gz"):
        data = (dist / name).read_bytes()
        lines.append(f" {hashlib.sha256(data).hexdigest()} {len(data)} {name}")
    (dist / "Release").write_text("\n".join(lines) + "\n", encoding="utf-8")


def upload_index(stanzas, dist):
    write_index(stanzas, dist)
    for name in ("Packages", "Packages.gz", "Release"):
        gh("release", "upload", "stable", str(dist / name), "--clobber")
    print(f"index: {len(stanzas)} packages")


class Pools:
    def __init__(self):
        tags = releases()
        self.ids = {int(t[5:]): rid for t, rid in tags.items() if re.fullmatch(r"pool-\d+", t)}
        self.assets = {n: assets(rid) for n, rid in self.ids.items()}

    def find(self, name):
        for n, existing in self.assets.items():
            if name in existing:
                return n, existing[name]
        return None, None

    def with_room(self):
        for n in sorted(self.assets):
            if len(self.assets[n]) < POOL_CAPACITY:
                return n
        n = max(self.assets, default=0) + 1
        gh("release", "create", f"pool-{n}", "--title", f"Ditto terminal packages, pool {n}",
           "--notes", "Package files for the stable release's index; see the README.",
           "--latest=false")
        self.ids[n] = releases()[f"pool-{n}"]
        self.assets[n] = {}
        return n

    def upload(self, n, files):
        delay = 30
        for _ in range(8):
            todo = [f for f in files if self.assets[n].get(f.name, (None,))[0] != f.stat().st_size]
            if not todo:
                return
            for f in todo:
                if f.name in self.assets[n]:
                    # What's left of an upload that broke off.
                    gh("api", "-X", "DELETE", f"repos/{REPO}/releases/assets/{self.assets[n][f.name][1]}")
            p = subprocess.run(["gh", "release", "upload", f"pool-{n}", *map(str, todo)],
                               capture_output=True, text=True)
            if p.returncode == 0:
                self.assets[n].update({f.name: (f.stat().st_size, None) for f in todo})
                return
            print(f"pool-{n}: {p.stderr.strip()[-400:]}", file=sys.stderr)
            time.sleep(delay)
            delay = min(delay * 2, 900)
            self.assets[n] = assets(self.ids[n])
        raise SystemExit(f"pool-{n}: couldn't upload {', '.join(f.name for f in files)}")


def main():
    artifacts, work = Path(sys.argv[1]), Path(sys.argv[2])
    shutil.rmtree(work, ignore_errors=True)
    debs_dir = work / "debs"
    debs_dir.mkdir(parents=True)
    # With one artifact, download-artifact puts its files in the directory itself.
    for archive in sorted(artifacts.rglob("debs.tar")):
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                if member.isfile() and member.name.endswith(".deb"):
                    member.name = os.path.basename(member.name)
                    tar.extract(member, debs_dir, filter="data")
    results = [line.split("\t") for path in sorted(artifacts.rglob("results.tsv"))
               for line in path.read_text().splitlines() if line]
    logs = {log.stem: log for log in artifacts.rglob("logs/*.log")}

    index = parse_index(download("stable", "Packages", work) .read_text(encoding="utf-8"))
    new = {}
    for deb in sorted(debs_dir.glob("*.deb")):
        package, version = run("dpkg-deb", "-W", "--showformat=${Package}\t${Version}", str(deb)).split("\t")
        if package in index and version_of(index[package]) == version:
            continue
        target = debs_dir / asset_name(deb.name)
        if target != deb:
            if target.exists():
                raise SystemExit(f"{deb.name} and another package would both be {target.name}")
            deb.rename(target)
        new[package] = target
    print(f"{len(new)} new packages from {len(results)} builds")

    pools = Pools()
    staged = work / "staged"
    pending = set()
    staged_count = 0

    def stage(n, f):
        nonlocal staged_count
        (staged / f"pool-{n}").mkdir(parents=True, exist_ok=True)
        os.link(f, staged / f"pool-{n}" / f.name)
        pending.add(n)
        staged_count += 1

    def flush():
        nonlocal staged_count
        if not pending:
            return
        for n in sorted(pending):
            index.update(parse_index(run("dpkg-scanpackages", "--multiversion", f"pool-{n}", "/dev/null", cwd=staged)))
        upload_index(index, work / "stable")
        shutil.rmtree(staged)
        pending.clear()
        staged_count = 0

    uploads = []
    for f in sorted(new.values()):
        home, existing = pools.find(f.name)
        if home is not None and existing[0] == f.stat().st_size:
            # Uploaded by a publish that stopped before the index went up.
            stage(home, f)
            continue
        if home is not None:
            gh("api", "-X", "DELETE", f"repos/{REPO}/releases/assets/{existing[1]}")
            del pools.assets[home][f.name]
        uploads.append(f)
    i = 0
    while i < len(uploads):
        n = pools.with_room()
        batch = uploads[i:i + min(UPLOAD_BATCH, POOL_CAPACITY - len(pools.assets[n]))]
        pools.upload(n, batch)
        for f in batch:
            stage(n, f)
        i += len(batch)
        if staged_count >= INDEX_EVERY:
            flush()
    flush()

    state_path = download("ci", "state.json", work)
    state = json.loads(state_path.read_text()) if state_path else {}
    failed = state.setdefault("failed", {})
    inflight = state.setdefault("inflight", {})
    built = set(state.get("built", []))
    run_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{REPO}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"
    report = []
    for pkg, status, *_ in results:
        if status == "skipped":
            continue
        inflight.pop(pkg, None)
        if status == "ok":
            failed.pop(pkg, None)
            if pkg not in index:
                built.add(pkg)
            continue
        entry = failed.setdefault(pkg, {"attempts": 0})
        entry["attempts"] += 1
        entry["status"] = status
        entry["run"] = run_url
        if pkg in logs:
            entry["log"] = logs[pkg].read_text(errors="replace").splitlines()[-40:]
        report.append(f"{pkg}: {status} (attempt {entry['attempts']})")
    state["built"] = sorted(built)
    state_file = work / "state.json"
    state_file.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
    gh("release", "upload", "ci", str(state_file), "--clobber")

    summary = [f"Uploaded {len(new)} packages; the index has {len(index)}."]
    if report:
        summary += ["", "Failed:", *(f"- {line}" for line in report)]
    print("\n".join(summary))
    if "GITHUB_STEP_SUMMARY" in os.environ:
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("\n".join(summary) + "\n")


if __name__ == "__main__":
    main()
