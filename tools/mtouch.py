"""Minitouch-backed multi-touch injection, replacing the raw `cat > /dev/input/event4` writer.

Why not the raw writer: `adb shell cat > node` is a child of the adb shell stream with no failure
semantics at all. A 90 s probe at the real event rate killed it 360 times while `adb exec-in dd`
survived 91698 writes without one failure, and every death drops the notes scheduled in that
window -- which is what "漏键" looked like, not bad timing (the scheduler's own error was 0.00 ms).

Why minitouch specifically: the daemon owns the node for the whole song, so the host never
re-opens anything mid-run; contacts are addressed by number instead of by MT-B slot, so a crashed
run cannot leave a phantom finger down; and this EvATive7 build echoes a `jlog` record with
device-side start/end timestamps for every command, which is both a latency measurement and proof
that a reset actually reached the device.
"""

from __future__ import annotations

import json
import random
import socket
import string
import subprocess
import threading
import time
from collections import deque

from locate import (ADB, CREATE_NO_WINDOW, DEVICE, TEXT, endpoint_gone,  # 路径集中探测：见 locate.py
                    MINITOUCH as LOCAL_BINARY, reconnect)
REMOTE = "/data/local/tmp/minitouch_bang"
PRESSURE = 50        # the node advertises max_press 0, so this is only ever a placeholder
# CREATE_NO_WINDOW / TEXT / endpoint_gone / reconnect now live in locate.py (2026-10-16): the frame
# reads in detect.capture hit the same dropped-endpoint failure the taps did, so the repair is
# shared instead of copied. The names are re-exported here unchanged -- `mtouch.TEXT` and
# `mtouch._endpoint_gone` are what the probes and `_adb` below use.


def _endpoint_gone(text: str) -> bool:
    """Shim: the judgement moved to `locate.endpoint_gone` (see there for why). Kept as a name
    because `_adb` and the probes read it here."""
    return endpoint_gone(text)


class MTouch:
    """A long-lived minitouch daemon reached through one `adb forward`ed TCP socket."""

    def __init__(self, serial: str = DEVICE, log=print) -> None:
        self.serial = serial
        self.log = log
        self.proc = None
        self.sock = None
        self.name = ""
        self.port = 0
        self.max_contacts = 10
        self.max_x = 720
        self.max_y = 1280
        self.pid = 0
        self.jlog: deque[dict] = deque(maxlen=4096)
        self.writes = 0
        # How many command lines we handed the socket against how many the device has echoed
        # back. `sendall` returning only proves the bytes reached the TCP buffer, so a channel that
        # is quietly falling behind looks exactly like a punctual one in the scheduler's own
        # numbers -- the difference is this subtraction, and it is the one that says whether a
        # MISS flood is our clock or the device's queue.
        self.cmds = 0
        self.echoes = 0
        # Named to match what the callers already report: every increment is a window in which
        # the schedule kept firing into a channel that was not there, i.e. dropped notes.
        self.respawns = 0
        self._dead = threading.Event()
        # RLock: a repair inside send() rebuilds the daemon, and open()/reset() call send() again
        # on this same thread. Other threads just wait out the repair.
        self._lock = threading.RLock()
        self._repairing = False
        self._client_warned = False
        self._t0 = time.time()
        self.open()

    # ---------- lifecycle ----------

    def _connect(self) -> bool:
        """Re-register a dropped TCP adb endpoint. Client-side bookkeeping only: nothing on the
        device is touched, and an endpoint that is already there answers "already connected".

        The machinery moved to `locate.reconnect` on 2026-10-16 (detect.capture heals the same
        way now); the three log lines are unchanged, which is what `probes/mtdiag.py` PART 3 reads.
        """
        return reconnect(self.serial, log=self.log)

    def _adb(self, *args: str) -> subprocess.CompletedProcess:
        # CREATE_NO_WINDOW: under pythonw a console child otherwise pops its own console window;
        # it is a process-creation flag only, the adb I/O and the daemon's stderr pipe are
        # unaffected (the minitouch banner is still read from stderr below).
        #
        # `timeout=`: every repair in this file comes through here (`ls`, `push`, `chmod`,
        # `forward`, `kill`), and these run inside the fire loop's own restart cycle. Without a
        # bound, one wedged adb client froze the round with the fingers still on the glass and the
        # panel showing a live LIVE until the user pressed 强制终止 -- the only other clock in the
        # whole harness that had no deadline. 30 s is far above the ~33 ms a tap costs and above
        # the slowest legitimate `push`; a TimeoutExpired propagates as the honest failure.
        r = subprocess.run([ADB, "-s", self.serial, *args], capture_output=True,
                           creationflags=CREATE_NO_WINDOW, timeout=30, **TEXT)
        if r.returncode != 0 and _endpoint_gone(r.stderr) and self._connect():
            # One retry, written out rather than recursive: the endpoint registration is the only
            # thing that was missing, and if it is still missing afterwards the caller sees adb's
            # own first failure instead of a repair loop. Every adb call in this file comes through
            # here, so an emulator restarted between rounds heals at open() -- no manual adb.
            r = subprocess.run([ADB, "-s", self.serial, *args], capture_output=True,
                               creationflags=CREATE_NO_WINDOW, timeout=30, **TEXT)
        return r

    def _ensure_pushed(self) -> None:
        if self._adb("shell", f"ls {REMOTE}").returncode == 0:
            return
        # adb is a Windows binary, so it needs the Windows spelling of the local path.
        r = self._adb("push", LOCAL_BINARY, REMOTE)
        if r.returncode != 0:
            raise RuntimeError(f"could not push minitouch: {r.stderr.strip()}")
        self._adb("shell", f"chmod 777 {REMOTE}")

    def open(self) -> None:
        """Start the daemon and prove the socket is usable before returning."""
        # close()/rebuild set the old event to stop the previous drain thread; a fresh daemon
        # needs a fresh (clear) one or the new pump would exit on its first loop check.
        self._dead = threading.Event()
        self._ensure_pushed()
        self.name = "mt" + "".join(random.choice(string.ascii_lowercase) for _ in range(7))
        # stdin=DEVNULL: the daemon must not be tied to any host pipe, since that coupling is
        # exactly what killed the previous writer.
        self.proc = subprocess.Popen(
            [ADB, "-s", self.serial, "shell", f"{REMOTE} -n {self.name}"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW, **TEXT,
        )
        ready = None
        end = time.perf_counter() + 8.0
        while time.perf_counter() < end and ready is None:
            line = self.proc.stderr.readline()
            if not line:
                break
            if "Type B touch device" in line or "touch device" in line:
                ready = line.strip()
            elif "detected on" in line:
                ready = line.strip()
        if ready is None:
            raise RuntimeError(f"minitouch never reported a touch device (rc={self.proc.poll()})")
        self.log(f"  minitouch: {ready}")
        self.port = 25900 + random.randrange(500)
        r = self._adb("forward", f"tcp:{self.port}", f"localabstract:{self.name}")
        if r.returncode != 0:
            raise RuntimeError(f"adb forward failed: {r.stderr.strip()}")
        self.sock = socket.create_connection(("127.0.0.1", self.port), timeout=3.0)
        self.sock.settimeout(0.5)
        if not self._read_banner():
            raise RuntimeError("minitouch daemon gave no banner")
        self._start_pump()
        self.reset()

    def _read_banner(self) -> bool:
        """Consume the `v` / `^ max_contacts max_x max_y max_press` / `$ pid` advertisement.

        Returns False when no `$ pid` arrived -- the port is open but nothing behind it talks,
        which is what a stale `adb forward` to a dead daemon looks like.
        """
        self.sock.sendall(b"v\n")
        buf = b""
        end = time.perf_counter() + 1.5
        while time.perf_counter() < end:
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                break
            buf += chunk
            if b"$" in buf and buf.count(b"\n") >= 3:
                break
        for line in buf.decode(errors="replace").splitlines():
            if line.startswith("^ "):
                f = line.split()
                self.max_contacts, self.max_x, self.max_y = int(f[1]), int(f[2]), int(f[3])
            elif line.startswith("$ "):
                # minitouch reports its own pid, which is the only clean way to stop it: killing
                # the local adb client leaves the daemon orphaned on the device, and a second
                # live daemon means two writers fighting over the same node.
                self.pid = int(line.split()[1])
        return b"$ " in buf

    def _start_pump(self) -> None:
        """Install a reader for the socket that is live right now.

        One reader per socket, started wherever a socket is installed (open/reconnect), and
        retired when its socket is no longer the live one -- never adopted across a swap.
        """
        self._dead = threading.Event()
        threading.Thread(target=self._pump, args=(self.sock,), daemon=True).start()

    def _pump(self, sock) -> None:
        """Keep reading `sock`, or the daemon's output buffer fills and command execution blocks.

        This is the failure mode the reference implementation calls out explicitly: an unread
        socket looks like the game ignoring taps, not like a stuck pipe. The loop is bound to
        ONE socket object and exits as soon as it is no longer `self.sock`: the earlier shape
        re-read `self.sock` each iteration and died on the old socket's close during a
        reconnect, leaving the reconnected channel with NO reader at all -- every later echo
        check then read "device is silent" and forced a full daemon rebuild (t93: 14 respawns
        in one restart cycle, each rebuilt channel healthy until the next reconnect orphaned
        it again; mtdiag.py reproduces pumps 2->0 across one reconnect).
        """
        buf = b""
        while not self._dead.is_set() and self.sock is sock:
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode(errors="replace").strip()
                if text.startswith("jlog "):
                    self.echoes += 1
                    try:
                        self.jlog.append(json.loads(text[5:]))
                    except json.JSONDecodeError:
                        pass

    def close(self) -> None:
        self._dead.set()
        # Raw sendall, not send(): a dying channel must not trigger a repair that would stand a
        # new daemon up while we are trying to shut this one down.
        try:
            if self.sock is not None:
                self.sock.sendall(b"r\n")
        except OSError:
            pass
        for closer in (getattr(self, "sock", None), getattr(self.proc, "stderr", None)):
            try:
                if closer is not None:
                    closer.close()
            except OSError:
                pass
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3.0)
            except Exception:
                self.proc.kill()
        # The adb client is only the tunnel; the daemon itself keeps running without it, so it is
        # killed by the pid it advertised.
        if self.pid:
            self._adb("shell", f"kill {self.pid} 2>/dev/null")
            self.pid = 0
        if self.port:
            self._adb("forward", "--remove", f"tcp:{self.port}")

    # ---------- commands ----------

    def send(self, lines: list[str]) -> None:
        self.send_bytes(("\n".join(lines) + "\n").encode(), len(lines))

    def send_bytes(self, payload: bytes, nlines: int = 1) -> None:
        """The fire loop's hot path: one pre-encoded frame, no list, no join, no encode.

        3000-odd actions a song at up to 60 a second: the two string round trips `send()` does per
        action (join + encode) are pure allocation on the very thread that has to hit a deadline,
        and every allocation is another chance for the collector to be asked for memory. The
        templates are built by the callers (`touch_down`/`move`/`up`), so this is just the
        transport: same retry, same repair, same counters as `send()`.
        """
        with self._lock:
            for _ in range(3):
                # The local `adb shell` client owns only the daemon's stdio; commands ride the
                # forwarded socket to `localabstract:<name>`, and the daemon deliberately survives
                # client death. g008 died here -- a transient adb-layer event killed the client and
                # the poll check called it fatal before the channel was even tried. Only the
                # device's own echo (see probe()) can say the channel is down.
                if (self.proc is not None and self.proc.poll() is not None
                        and not self._client_warned):
                    self._client_warned = True
                    self.log("  minitouch: adb shell client exited; socket channel keeps going")
                try:
                    if self.sock is None:
                        raise OSError("no socket to send on")
                    self.sock.sendall(payload)
                    self.writes += nlines
                    self.cmds += nlines
                    return
                except OSError:
                    if not self._repairing:
                        self._repairing = True
                        try:
                            self.recover()
                        finally:
                            self._repairing = False
            raise RuntimeError("minitouch socket will not accept commands")

    def reconnect(self) -> None:
        """Re-open the socket only. The daemon survives, so the node is never re-acquired.

        Closing a socket makes minitouch drop its contacts, which is the outcome we want here:
        a reconnect must not resume with fingers still pressed.
        """
        sock, self.sock = self.sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        end = time.perf_counter() + 5.0
        last = None
        while time.perf_counter() < end:
            try:
                self.sock = socket.create_connection(("127.0.0.1", self.port), timeout=3.0)
                self.sock.settimeout(0.5)
                if not self._read_banner():
                    # The daemon answers a connect with its banner within milliseconds. TCP
                    # accepted but silent means nothing is behind the forward -- adb keeps the
                    # port open for a `localabstract` that no longer exists -- and no socket
                    # retry can heal that, only a rebuild can, so fail fast.
                    raise RuntimeError("connected but no minitouch banner")
                self._start_pump()
                return
            except RuntimeError as exc:
                raise RuntimeError(f"no minitouch behind tcp:{self.port} ({exc})")
            except OSError as exc:
                last = exc
                time.sleep(0.2)
        raise RuntimeError(f"minitouch socket will not reconnect ({last!r})")

    def probe(self) -> bool:
        """Round-trip one commit and require the device to have echoed it.

        The echo is device-side proof that the command arrived; the local adb client's liveness
        says nothing (see send()). A silent echo gets one full repair before the verdict, so a
        False here means the channel is genuinely down.
        """
        if self._echo():
            return True
        try:
            self.recover()
        except RuntimeError:
            return False
        return self._echo()

    def _echo(self, wait: float = 0.5) -> bool:
        """Watch the monotonic `echoes` counter, never `len(self.jlog)`.

        jlog is a deque(maxlen=4096): after a long attempt (t93/t94: ~2400 fired actions =
        ~4800 command lines) it saturates, `len()` stops changing, and an echo check that
        watched the length read "device is silent" FOREVER -- across reconnects and rebuilds
        (the deque survives both), forcing a daemon rebuild at every probe while the play
        phases on those same daemons echoed fine. `echoes` is monotonic and cannot saturate.
        """
        n = self.echoes
        try:
            self.send(["c"])
        except RuntimeError:
            return False
        end = time.perf_counter() + wait
        while time.perf_counter() < end and self.echoes == n:
            time.sleep(0.005)
        return self.echoes > n

    def recover(self) -> None:
        """Repair whichever layer is down: socket first (cheap), daemon rebuild if that fails.

        Reconnect alone is enough when only the socket or a forward dropped; the daemon owns the
        touch node for the whole song and should not be restarted casually. If the reconnected
        channel stays silent, the daemon itself is gone and only a fresh one can play.
        """
        # Counted here, once per repair: this is the window in which the schedule had no
        # working channel (callers compare respawns around a burst to measure mid-song holes).
        self.respawns += 1
        try:
            self.reconnect()
            if self._echo(0.6):
                self.log("  minitouch: socket re-established (device echo verified)")
                return
            self.log("  minitouch: reconnected but the device is silent - rebuilding the daemon")
        except RuntimeError as exc:
            self.log(f"  minitouch: reconnect failed ({exc}) - rebuilding the daemon")
        self._rebuild()

    def _rebuild(self) -> None:
        """Stand up a completely fresh daemon: new name, port, forward and socket."""
        self._dead.set()                       # stop the old drain thread
        sock, self.sock = self.sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        # Stop the old daemon by its advertised pid before a new one opens the same node; it may
        # already be gone, in which case the kill is a no-op.
        if self.pid:
            self._adb("shell", f"kill {self.pid} 2>/dev/null")
            self.pid = 0
        if self.port:
            self._adb("forward", "--remove", f"tcp:{self.port}")
            self.port = 0
        proc, self.proc = self.proc, None
        if proc is not None:
            try:
                proc.kill()
                proc.wait(timeout=3.0)
            except Exception:
                pass
        self.open()
        self.log("  minitouch: daemon rebuilt")

    def reset(self) -> None:
        """Lift every contact and wait for the device to confirm it."""
        self.send(["r", "c"])
        end = time.perf_counter() + 0.5
        while time.perf_counter() < end:
            if any(e.get("cmd") == "r" for e in list(self.jlog)[-16:]):
                return
            time.sleep(0.005)

    # ---------- the interface player.py already speaks ----------
    #
    # Payloads are byte templates, built with `%` straight into the frame the daemon wants (`c`
    # commits it). This is the per-action path of a song -- see `send_bytes` for why it does not go
    # through `send()`'s str list.

    def touch_down(self, slot: int, x: int, y: int, tracking_id: int = 0) -> None:
        self.send_bytes(b"d %d %d %d %d\nc\n" % (slot, x, y, PRESSURE), 2)

    def touch_move(self, slot: int, x: int, y: int) -> None:
        self.send_bytes(b"m %d %d %d %d\nc\n" % (slot, x, y, PRESSURE), 2)

    def touch_up(self, slot: int) -> None:
        self.send_bytes(b"u %d\nc\n" % slot, 2)

    def syn(self) -> None:
        self.send(["c"])

    def release_all(self, slots: int = 0) -> None:
        self.reset()

    # ---------- measurement ----------

    def command_costs(self, prefix: str) -> list[float]:
        return [e["c"] for e in self.jlog if str(e.get("cmd", "")).startswith(prefix)]

    def clock_offset_ms(self) -> float | None:
        """device_epoch_ms - host_epoch_ms, from the newest jlog echo."""
        if not self.jlog:
            return None
        e = self.jlog[-1]
        return e["st"] - time.time() * 1000.0


def adb_tap(x: float, y: float, serial: str = DEVICE, timeout: float = 15.0) -> float:
    """One tap through `adb shell input tap`, returning how long the call took.

    The 随机选曲 pill on 乐曲选择 is the one control minitouch cannot press: nine taps across a
    grid plus 400 ms and 1200 ms holds left the selection untouched and the pill never painted
    its pressed state, while this call re-picked the song on every one of four tries (33/34/33/33
    ms measured 2026-09-29). Everything else stays on the daemon -- a call here opens its own adb
    connection, and the daemon's socket is long-lived, so the two never contend.
    """
    t = time.perf_counter()
    subprocess.run([ADB, "-s", serial, "shell", "input", "tap", str(int(x)), str(int(y))],
                   capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW)
    return time.perf_counter() - t


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "tools")
    from inject import to_raw

    inj = MTouch()
    try:
        print(f"contacts {inj.max_contacts} surface {inj.max_x}x{inj.max_y} "
              f"clock offset {inj.clock_offset_ms():+.1f} ms")
        print("probe ->", inj.probe())
        if len(sys.argv) > 3:
            sx, sy = int(sys.argv[2]), int(sys.argv[3])
            rx, ry = to_raw("MEASURED", sx, sy)
            print(f"tapping screen ({sx},{sy}) -> surface ({rx},{ry})")
            inj.touch_down(0, rx, ry)
            time.sleep(0.15)
            inj.touch_up(0)
            time.sleep(0.4)
        costs = inj.command_costs("d") + inj.command_costs("m") + inj.command_costs("c")
        if costs:
            costs.sort()
            print(f"command cost ms: n={len(costs)} p50 {costs[len(costs)//2]:.3f} "
                  f"max {costs[-1]:.3f}")
    finally:
        inj.close()
        print("closed")
