"""Every frame's HUD counter box, at the capture's own cadence, for the counting-rule study.

#111 -- how many judged objects one long note contributes -- is the one open question with all its
instrumentation but one input: a full-rate recording of the five counters, read frame by frame.
The evidence frames the watcher saves are one per *event*, and the event is the thing being
counted: they cannot answer it. Everything else already exists (the reader, its regression, the
framework), so this file is the missing input and nothing more.

**Why the box and not the screen.** Measured on this machine: a 90x120 crop through FFV1 is
0.73 ms/frame and lossless; mp4v is 3.3 ms but *corrupts the digits* (max channel delta 63, 2028
pixels over threshold inside the counter block) and 720p FFV1 is 17.3 ms/frame, which cannot keep
up with a 9 ms capture cadence. The screen would also be 200x the bytes to answer a question about
five numbers.

**Why the readings are not in the recording.** `hudread.counters_arr` costs 93.6 ms a frame (it is
a template reader, not arithmetic), so reading 16k frames during a round would cost a core. The
pixels go down lossless; the reading is an offline pass over the transitions.

`<tag>.counters.avi` is that lossless crop. `<tag>.counters.jsonl` carries `{"i", "t"}` per frame
-- the capture's own stamps, so a frame index is a millisecond and the study can line the counters
up against the chart and the fire log.
"""

import json
import os
import queue
import threading
import time

import numpy as np

# Covers PERFECT (y 137..152) through MISS (y 225..243), digits x 1148..1190, with slack on both
# sides: hudread's rows and hudwatch's X0/X1 are read off this crop, never the other way round.
BOX = (1100, 130, 1190, 250)
NOMINAL_FPS = 30


class CountersRecorder:
    """start() is implicit on first offer; call close() and read `stats()`.

    One writer thread. `offer()` runs on the sampling thread and must not do I/O: it crops and
    hands the array to a bounded queue, and when the queue is full it *drops* and counts the drop.
    A recorder that could stall the capture would cost a round's accuracy to save a diagnostic.
    """

    def __init__(self, path, box=BOX, queue_max=600, log=print):
        self.path = path
        self.box = box
        self.log = log
        self.frames = 0
        self.dropped = 0
        self.error = None
        self._q = queue.Queue(maxsize=queue_max)
        self._writer = None
        self._t0 = None

    def start(self):
        import cv2

        x0, y0, x1, y1 = self.box
        self._vw = cv2.VideoWriter(self.path, cv2.VideoWriter_fourcc(*"FFV1"), NOMINAL_FPS,
                                   (x1 - x0, y1 - y0))
        if not self._vw.isOpened():
            raise RuntimeError(f"FFV1 writer would not open {self.path}")
        self._idx = open(os.path.splitext(self.path)[0] + ".jsonl", "w", encoding="utf-8",
                         buffering=1)
        self._t0 = time.perf_counter()
        self._writer = threading.Thread(target=self._writer_loop, daemon=True)
        self._writer.start()
        return self

    def offer(self, t, img):
        """Sampling thread: crop, enqueue, return. No allocation beyond the crop's own bytes."""
        x0, y0, x1, y1 = self.box
        try:
            self._q.put_nowait((t, np.ascontiguousarray(img[y0:y1, x0:x1])))
        except queue.Full:
            self.dropped += 1

    def _writer_loop(self):
        while True:
            item = self._q.get()
            if item is None:
                return
            t, crop = item
            try:
                self._vw.write(crop)
                self._idx.write(json.dumps({"i": self.frames, "t": round(t, 4)}) + "\n")
                # Counted only with the write: `frames` is the frame *index* the jsonl records and
                # the number `stats()` reports, so incrementing it on a failed write made the two
                # disagree -- every later timestamp would point one frame early in the .avi, and
                # the whole point of this file is that a frame index is a millisecond.
                self.frames += 1
            except Exception as e:                                  # noqa: BLE001 - diagnostic
                self.error = e
                self.dropped += 1

    def close(self, timeout=6.0):
        if self._writer is None:
            return self.stats()
        self._q.put(None)
        self._writer.join(timeout)
        self._vw.release()
        self._idx.close()
        return self.stats()

    def stats(self):
        try:
            size = os.path.getsize(self.path)
        except OSError:
            size = 0
        return {"path": self.path, "frames": self.frames, "dropped": self.dropped,
                "seconds": (time.perf_counter() - self._t0) if self._t0 else 0.0,
                "bytes": size, "error": self.error}

    def line(self):
        """The one sentence the round log carries -- same shape as the HUD tally's."""
        s = self.stats()
        return (f"计数器实录：{s['frames']} 帧 / {s['bytes'] / 1e6:.1f} MB -> {s['path']}"
                + (f"（写手来不及，丢 {s['dropped']} 帧）" if s["dropped"] else "")
                + (f"（写盘出错 {s['error']!r}）" if s["error"] else ""))
