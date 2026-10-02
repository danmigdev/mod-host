#!/usr/bin/env python3
"""Record all fetched MOD/MODEP branch pins and their integration decisions."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = "f14a230bf48b42035406d2b2dca038efa4d2abca"


def git(*arguments):
    return subprocess.check_output(["git", *arguments], cwd=ROOT, text=True).strip()


def decision(branch, unique):
    if unique == 0:
        return "The branch is already an ancestor of the selected MOD master."
    name = branch.split("/", 1)[1]
    if name == "modep":
        return "The only unique commit removes GitHub Actions; it adds no runtime capability."
    if name == "jack_metadata":
        return "Legacy audio-port pretty-name prototype; the current host already handles JACK metadata and Grid owns display names."
    if name == "midi-control":
        return "Legacy MIDI-control prototype superseded by current MIDI learn/map/unmap and property handling."
    if name == "temposync":
        return "Legacy embedded Link/ASIO implementation superseded by current transport/MIDI sync and optional Hylia integration."
    if name == "save_session":
        return "Legacy session-saving prototype superseded by MOD UI pedalboards and current LV2 state/preset commands."
    if name == "dwarf-pin-core0":
        return "Dwarf-specific CPU affinity is not appropriate for Raspberry Pi 4/Pisound."
    if name == "external-ui":
        return "Initial external-UI prototype; current master already has external-UI support and Grid uses browser plugin skins."
    if name == "midi_event":
        return "Prototype socket MIDI injection is unnecessary for JACK/Pisound MIDI; its parsing/error handling needs further work."
    if name.startswith("hotfix-"):
        return "Stable buffer-change lifecycle fix selected from hotfix-1.13; other fixes are equivalent/superseded or target extra MOD playback ports and old Control Chain APIs."
    return "Portable socket, worker, BPM and Lilv fixes selected individually; remaining coupled preload/multi-command/monitoring and rk358x/Pablito changes deferred."


def audit():
    selected = []
    for revision in git("rev-list", "--reverse", f"{BASE}..HEAD").splitlines():
        message = git("show", "-s", "--format=%B", revision)
        marker = "(cherry picked from commit "
        if marker in message:
            upstream = message.split(marker, 1)[1].split(")", 1)[0]
            selected.append({"upstream_revision": upstream, "local_revision": revision,
                             "subject": message.splitlines()[0]})

    branches = []
    candidates = {}
    for line in git("for-each-ref", "--format=%(refname:short)\t%(objectname)\t%(symref)", "refs/remotes").splitlines():
        fields = line.split("\t")
        if len(fields) > 2 and fields[2]:
            continue
        branch, revision = fields[:2]
        behind, ahead = map(int, git("rev-list", "--left-right", "--count", f"{BASE}...{branch}").split())
        patches = git("log", "--cherry-pick", "--right-only", "--no-merges", "--format=%H", f"{BASE}...{branch}").splitlines()
        branches.append({"branch": branch, "revision": revision, "commits_behind_base": behind,
                         "commits_ahead_of_base": ahead, "patch_unique_commit_count": len(patches),
                         "decision": decision(branch, ahead)})
        for patch in patches:
            candidates.setdefault(patch, []).append(branch)

    selected_revisions = {entry["upstream_revision"] for entry in selected}
    return {"audit_date": "2026-10-03", "target": "Raspberry Pi 4 / Pisound / Patchbox OS 64-bit",
            "integration_branch": "rpi4-pisound-integration", "base_revision": BASE,
            "remotes": {"origin": git("remote", "get-url", "origin"), "modep": git("remote", "get-url", "modep")},
            "branches": branches, "selected_upstream_commits": selected,
            "candidate_commits": [{"revision": revision, "branches": refs,
                                   "decision": "selected" if revision in selected_revisions else "deferred_or_superseded"}
                                  for revision, refs in sorted(candidates.items())],
            "local_changes": ["NUL-delimited TCP framing preserves incomplete commands across reads.",
                              "Disconnected writes return errors without infinite retry loops or SIGPIPE on Linux.",
                              "LF checkout attributes keep build scripts usable from Windows checkouts.",
                              "Isolated JACK/LV2/audio/MIDI/socket/worker integration checks."],
            "validation": {"environment": "WSL2 Ubuntu 24.04 x86_64; GCC 13; JACK 1.9.21; Lilv 0.24.22; LV2 1.18.10",
                           "commands": ["make -j2", "make integration-test"],
                           "hardware_validation": "Raspberry Pi ARM64 compilation and physical Pisound latency/MIDI testing remain to be run on the target.",
                           "optional_dependencies": "Ableton Link requires Hylia; aggregated MIDI requires mod-midi-merger; Control Chain requires cc_client."}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    document = json.dumps(audit(), indent=2) + "\n"
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(document, encoding="utf-8")
    else:
        print(document, end="")
