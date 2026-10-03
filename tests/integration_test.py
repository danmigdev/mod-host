#!/usr/bin/env python3
"""Exercise the real host with an isolated JACK dummy server and LV2 examples."""
import math
import os
from pathlib import Path
import shlex
import socket
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


class Frames:
    def __init__(self, connection):
        self.connection = connection
        self.pending = b""
        connection.settimeout(3)

    def read(self):
        while b"\0" not in self.pending:
            chunk = self.connection.recv(65536)
            assert chunk, "Connection closed before a complete response"
            self.pending += chunk
        frame, self.pending = self.pending.split(b"\0", 1)
        return frame.decode()

    def command(self, command, expected="resp 0"):
        self.connection.sendall(command.encode() + b"\0")
        response = self.read()
        assert response == expected, (command, response, expected)
        return response

    def expect_pending(self):
        assert not self.pending, self.pending
        self.connection.settimeout(0.1)
        try:
            response = self.connection.recv(1024)
            raise AssertionError(f"Incomplete command produced a response: {response!r}")
        except socket.timeout:
            pass
        finally:
            self.connection.settimeout(3)


def free_port():
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        return reservation.getsockname()[1]


def compile_helpers(directory):
    flags = shlex.split(subprocess.check_output(
        ["pkg-config", "--cflags", "--libs", "jack", "lilv-0"], text=True))
    probe = directory / "jack-probe"
    worker = directory / "worker-response-test"
    sender = directory / "socket-send-test"
    subprocess.run(["cc", "-std=gnu99", "-Wall", "-Wextra", "-Werror",
                    str(ROOT / "tests/jack_probe.c"), "-o", str(probe), *flags, "-lm"], check=True)
    subprocess.run(["cc", "-std=gnu99", "-Wall", "-Wextra", "-Werror", "-pthread",
                    str(ROOT / "tests/worker_response_test.c"), str(ROOT / "src/worker.c"),
                    "-o", str(worker), *flags], check=True)
    subprocess.run([str(worker)], check=True, timeout=3)
    print("PASS worker response framing and incomplete-response deferral")
    subprocess.run(["cc", "-std=gnu99", "-Wall", "-Wextra", "-Werror",
                    str(ROOT / "tests/socket_send_test.c"), str(ROOT / "src/socket.c"),
                    "-o", str(sender), *flags], check=True)
    subprocess.run([str(sender)], check=True, timeout=3, capture_output=True)
    print("PASS disconnected socket write returns an error without blocking or SIGPIPE")
    return probe


def wait_for_jack(environment, process):
    for _ in range(100):
        assert process.poll() is None, "JACK exited during startup"
        result = subprocess.run(["jack_lsp"], env=environment, capture_output=True)
        if result.returncode == 0:
            return
        time.sleep(0.05)
    raise AssertionError("JACK did not start")


def connect_host(port, process):
    for _ in range(100):
        assert process.poll() is None, "mod-host exited during startup"
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=0.1)
        except OSError:
            time.sleep(0.05)
    raise AssertionError("mod-host did not accept a connection")


def check_protocol(frames):
    frames.command("add http://lv2plug.in/plugins/eg-amp 0")
    frames.command("param_get 0 gain", "resp 0 0.0000")
    frames.connection.sendall(b"\0\0param_set 0 gain 3\0param_get 0 gain\0\0")
    assert frames.read() == "resp 0"
    assert frames.read() == "resp 0 3.0000"

    frames.connection.sendall(b"param_se")
    frames.expect_pending()
    frames.connection.sendall(b"t 0 gain 6\0")
    assert frames.read() == "resp 0"

    frames.connection.sendall(b"param_get 0 gain\0param_se")
    assert frames.read() == "resp 0 6.0000"
    frames.expect_pending()
    frames.connection.sendall(b"t 0 gain 0\0")
    assert frames.read() == "resp 0"

    for size in (1024, 2048, 8193):
        command = b"param_get 0 gain"
        frames.connection.sendall(command + b" " * (size - len(command) - 1) + b"\0")
        assert frames.read() == "resp 0 0.0000", size
    frames.connection.sendall(b"\0" * 2048 + b"param_get 0 gain\0")
    assert frames.read() == "resp 0 0.0000"

    # Exercise many complete frames split at arbitrary TCP packet boundaries.
    payload = b"param_get 0 gain\0" * 31
    for start in range(0, len(payload), 13):
        frames.connection.sendall(payload[start:start + 13])
    assert [frames.read() for _ in range(31)] == ["resp 0 0.0000"] * 31
    print("PASS coalesced/fragmented/empty frames and exact 1024/2048-byte commands")


def check_plugins(frames, feedback, probe, directory, environment):
    frames.command("connect system:capture_1 effect_0:in")
    frames.command("disconnect system:capture_1 effect_0:in")
    measured = float(subprocess.check_output([str(probe)], env=environment, text=True, timeout=10))
    assert math.isclose(measured, 0.125, abs_tol=0.001), measured
    print("PASS real JACK routing and LV2 audio processing")
    for buffer_size in (128, 512, 256):
        subprocess.run(["jack_bufsize", str(buffer_size)], env=environment, check=True, capture_output=True, timeout=5)
        frames.command("param_get 0 gain", "resp 0 0.0000")
    measured = float(subprocess.check_output([str(probe)], env=environment, text=True, timeout=10))
    assert math.isclose(measured, 0.125, abs_tol=0.001), measured
    print("PASS live JACK buffer changes preserve plugin/audio processing")

    frames.command("param_set 0 gain 5")
    preset = directory / "test-presets.lv2"
    frames.command(f'preset_save 0 "Integration Gain" "{preset}" gain.ttl')
    assert (preset / "gain.ttl").is_file()
    frames.command(f'bundle_add "{preset}/"')
    frames.command("param_set 0 gain 0")
    frames.command(f'preset_load 0 "{(preset / "gain.ttl").as_uri()}"')
    frames.command("param_get 0 gain", "resp 0 5.0000")

    frames.command("add http://lv2plug.in/plugins/eg-params 1", "resp 1")
    property_uri = "http://lv2plug.in/plugins/eg-params#int"
    frames.command(f"patch_set 1 {property_uri} 42")
    time.sleep(0.1)
    state = directory / "pedalboard-state"
    frames.command(f'state_save "{state}"')
    state_file = state / "effect-1/effect.ttl"
    assert state_file.is_file()
    assert "42" in state_file.read_text()
    frames.command(f"patch_set 1 {property_uri} 7")
    time.sleep(0.1)
    frames.command(f'state_load "{state}"')
    check_state = directory / "restored-state"
    frames.command(f'state_save "{check_state}"')
    assert "42" in (check_state / "effect-1/effect.ttl").read_text()
    print("PASS LV2 preset and patch/state save/restore")

    frames.command("midi_map 0 gain 0 7 -12 12", "resp 1")
    subprocess.run([str(probe), "midi"], env=environment, check=True, capture_output=True, timeout=10)
    frames.connection.sendall(b"param_get 0 gain\0")
    response = frames.read()
    expected = -12 + 24 * 64 / 127
    assert response.startswith("resp 0 "), response
    assert math.isclose(float(response.split()[2]), expected, abs_tol=0.01), response

    events = Frames(feedback)
    saw_midi = False
    for _ in range(50):
        event = events.read()
        saw_midi |= event.startswith("param_set 0 gain ")
        if event == "data_finish":
            frames.command("output_data_ready")
            if saw_midi:
                break
    assert saw_midi, "Missing MIDI parameter update on the feedback socket"
    frames.command("midi_unmap 0 gain", "resp 1")
    frames.command("set_bpm 300")
    frames.command("set_bpm 301", "resp -207")
    frames.command("transport 1 4 120")
    frames.command('transport_sync "midi"')
    frames.command('transport_sync "none"')
    frames.command("transport 0 4 120")
    print("PASS real MIDI CC mapping, feedback protocol and transport commands")


def main():
    assert (ROOT / "mod-host").is_file(), "Build mod-host with make first"
    environment = os.environ.copy()
    environment["JACK_DEFAULT_SERVER"] = f"modhost-integration-{os.getpid()}"
    environment["LV2_PATH"] = os.environ.get("LV2_PATH", "/usr/lib/lv2")
    command_socket = feedback_socket = None
    host = jack = None
    with tempfile.TemporaryDirectory(prefix="modhost-integration-") as temp:
        directory = Path(temp)
        probe = compile_helpers(directory)
        with (directory / "jack.log").open("w+") as jack_log, (directory / "host.log").open("w+") as host_log:
            try:
                jack = subprocess.Popen(["jackd", "--no-realtime", "--name", environment["JACK_DEFAULT_SERVER"],
                                         "-d", "dummy", "-r", "48000", "-p", "256"],
                                        env=environment, stdout=jack_log, stderr=subprocess.STDOUT)
                wait_for_jack(environment, jack)
                command_port, feedback_port = free_port(), free_port()
                while command_port == feedback_port:
                    feedback_port = free_port()
                host = subprocess.Popen([str(ROOT / "mod-host"), "-n", "-p", str(command_port), "-f", str(feedback_port)],
                                        cwd=ROOT, env=environment, stdout=host_log, stderr=subprocess.STDOUT)
                command_socket = connect_host(command_port, host)
                feedback_socket = connect_host(feedback_port, host)
                frames = Frames(command_socket)
                check_protocol(frames)
                check_plugins(frames, feedback_socket, probe, directory, environment)
                frames.command("remove -1")
                command_socket.sendall(b"param_se")
                command_socket.close()
                feedback_socket.close()
                command_socket = connect_host(command_port, host)
                feedback_socket = connect_host(feedback_port, host)
                reconnected = Frames(command_socket)
                command_socket.sendall(b"cpu_load\0")
                response = reconnected.read()
                assert response.startswith("resp 0 ") and float(response.split()[2]) >= 0, response
                assert host.poll() is None and jack.poll() is None
                print("PASS reconnect discards an unfinished command")
                print("All mod-host integration checks passed.")
            except Exception:
                for name, log in (("JACK", jack_log), ("mod-host", host_log)):
                    log.flush()
                    log.seek(0)
                    print(f"{name} log:\n{log.read()}")
                raise
            finally:
                for connection in (command_socket, feedback_socket):
                    if connection is not None:
                        connection.close()
                for process in (host, jack):
                    if process is not None and process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)


if __name__ == "__main__":
    main()
