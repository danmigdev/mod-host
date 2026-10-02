# Raspberry Pi 4 and Pisound integration

This branch starts from MOD Audio `master` at
`f14a230bf48b42035406d2b2dca038efa4d2abca`, keeps its MOD UI command protocol,
and selects ten portable fixes from the newer MOD development/hotfix branches.
The target is Raspberry Pi 4 with Pisound on 64-bit Patchbox OS.

The complete audit of every fetched MOD Audio and Blokas MODEP branch, including
full revision pins and selected upstream commits, is in
[integration-manifest.json](integration-manifest.json). Regenerate it with
`python3 utils/audit_branches.py --output docs/integration-manifest.json` after
reviewing changes to the remote branches.

## Selected changes

- Four upstream socket fixes handle multiple commands per read, padding, exact
  buffer boundaries and TCP_NODELAY. The local framing correction additionally
  retains incomplete NUL-terminated commands across arbitrary TCP reads and
  dispatches complete commands before a partial trailing command.
- Three worker fixes protect incomplete ringbuffer messages, lock response
  memory, and postpone incomplete worker responses to the next audio cycle.
- The supported tempo range now reaches 300 BPM, matching the Grid transport UI.
- The newer Lilv object-index option is used only when the installed headers
  expose it, preserving compatibility with distribution Lilv releases.
- The stable buffer-size hotfix deactivates/reactivates LV2 instances around
  options changes, preserving the plugin lifecycle during JACK buffer changes.
- Failed socket writes return an error. Linux writes use MSG_NOSIGNAL so a
  disconnected UI cannot terminate the host with SIGPIPE or trigger an endless
  retry loop. Checkout attributes preserve LF endings for build scripts.

MODEP `master`, `control-chain`, `cpu_load`, `ext_state`, `modep_2018.08` and
`temposync2` are ancestors of the selected MOD master. MODEP `modep` adds only
the removal of GitHub Actions. Its older MIDI, tempo/Link and session-save
prototypes have been superseded by the current MIDI/transport/state commands.
The old JACK pretty-name prototype is unnecessary for the Grid plugin names.

The newer `master-dg`, `pablito` and related branches include coupled preload,
parallel command, monitoring, HMI and rk358x hardware changes. Only the portable
fixes listed above are selected here. Dwarf CPU pinning, Pablito playback-port
assumptions, prototype socket MIDI injection, memfd binary loading and the
ongoing Lilv refactor need separate validation before use on Raspberry Pi.

## Building on the target

Use the native compiler on the 64-bit Raspberry Pi OS. Keep generic platform
defaults; MOD-device, Dwarf and rk358x build definitions do not describe Pisound.

```sh
sudo apt-get install --no-install-recommends build-essential pkg-config \
  libjack-jackd2-dev liblilv-dev libreadline-dev lv2-dev
make -j2
```

The build produces `mod-host`, `mod-host.so`, `fake-input.so` and
`mod-monitor.so`. Build and stage these for the existing MODEP service and JACK
setup; use the target device's configured service user, paths and ports. The
default command/feedback ports are 5555/5556 when both are explicitly enabled.
Replacing a system binary or JACK internal client requires a service restart;
the build itself does not alter the installed services.

Ableton Link requires Hylia to be available through pkg-config. Aggregated MIDI
requires the installed `mod-midi-merger` JACK client, and Control Chain requires
`cc_client`. These are optional compile/runtime dependencies, not capabilities
supplied by merging an old MODEP branch. Normal Pisound JACK MIDI routing and
MIDI CC mapping work without Control Chain or Hylia.

## Validation

```sh
sudo apt-get install --no-install-recommends jackd2 lv2-examples python3
make integration-test
```

The integration suite starts an isolated named JACK dummy server, launches the
real host on unused socket ports, and uses the LV2 example plugins. It checks
TCP fragmentation/coalescing, empty frames, exact 1024/2048-byte commands, larger
messages, partial-command reconnects, disconnected writes, worker response
framing, real audio samples, live JACK buffer changes, MIDI CC input/feedback,
transport, and LV2 preset/patch/state save and restore. It terminates its own
processes and leaves the device's normal JACK server alone.

These checks passed on WSL2 Ubuntu 24.04 x86_64 with GCC 13, JACK 1.9.21,
Lilv 0.24.22 and LV2 1.18.10. ARM64 compilation and physical Pisound audio/MIDI
latency testing still require the target device. Optional Hylia/Control Chain
code paths were not exercised by this test environment.
