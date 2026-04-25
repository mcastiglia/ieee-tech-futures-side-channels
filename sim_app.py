"""
sim_app.py — Hardware-free simulation of the Power Analysis demo
================================================================
This is the publishable version for attendees.  No ChipWhisperer scope,
no ARM GCC toolchain, and no target board are required.  Install three
Python packages and run:

    pip install flask numpy plotly
    python sim_app.py

Then open http://127.0.0.1:5001

HOW THE SIMULATION WORKS
-------------------------
The real firmware does an early-exit character comparison: it loops through
each byte of the guess and returns the moment one doesn't match.

  Correct character at position i  →  one more comparison iteration
                                   →  CPU runs for slightly longer
                                   →  slightly more power consumed
                                   →  measurable bump in the ADC trace

We reproduce this physics with a synthetic trace generator (_make_trace):

  1. Deterministic Gaussian noise seeded from the guess bytes.
     Same guess → same trace every call.  Different guesses have
     independent noise patterns, so the SAD winner is consistent.

  2. Power-supply ripple (low-frequency sinusoid).
     Identical across all traces; cancels when difference traces are computed,
     just like real hardware.

  3. A Gaussian power spike at offset (position + 1) * SAMPLES_PER_CHAR
     for every position where the guess matches DEMO_PASSWORD.
     The early-exit model: the loop body doesn't execute beyond the first
     mismatch, so no spike is added for positions after a wrong character.

The result is that every attack step (compare, sweep, diff, SAD, full attack)
works exactly as it does against real hardware — the correct character always
produces the highest SAD score.

DEMO PASSWORD
-------------
The simulated firmware is "protecting" the password defined by DEMO_PASSWORD
below.  You can change it to anything in CHARSET up to 8 characters.
"""

from __future__ import annotations

import threading
from typing import Any

import numpy as np
import plotly.graph_objects as go
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCOPETYPE = "SIMULATED"
PLATFORM  = "CWLITEARM (sim)"
SS_VER    = "SS_VER_2_1"
CHARSET   = "abcdefghijklmnopqrstuvwxyz0123456789"
MAX_SAMPLES     = 3000
DEFAULT_SAMPLES = 1000

# The password the simulated firmware is checking against.
# Change this to any string of characters from CHARSET (max 8 chars).
DEMO_PASSWORD = "h0px3"

# ---------------------------------------------------------------------------
# Trace simulation parameters
# ---------------------------------------------------------------------------
# Number of ADC samples consumed by one comparison iteration.
# This controls where each per-character spike appears on the time axis:
#   spike_center[pos] = (pos + 1) * _SAMPLES_PER_CHAR
#
# IMPORTANT: all spikes must land inside the DEFAULT_SAMPLES window so that
# the diff plot (Step 4) and sweep plot (Step 3) show complete spikes rather
# than clipped edges.  For a 5-character password with DEFAULT_SAMPLES=1000:
#   max spike = 5 * _SAMPLES_PER_CHAR  must be < 1000
#   → _SAMPLES_PER_CHAR < 200
# We use 175, placing the last spike at 875 — well clear of the boundary.
_SAMPLES_PER_CHAR: int   = 175

# Gaussian spike half-width in samples (sigma = this / 2.5).
_SPIKE_HALF_WIDTH: int   = 30

# Peak amplitude of a correct-character power spike.
# Must be large enough relative to _NOISE_STD to win the SAD contest reliably.
# Rule of thumb: _SPIKE_AMP / _NOISE_STD > 5 for a clearly visible diff plot.
_SPIKE_AMP: float        = 0.14

# Standard deviation of the base Gaussian noise floor.
_NOISE_STD: float        = 0.012

# Amplitude of the simulated power-supply ripple (common to all traces).
_RIPPLE_AMP: float       = 0.008

# Normalised ripple frequency (arbitrary units matching trace length).
_RIPPLE_FREQ: float      = 14.0


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

class SimState:
    def __init__(self) -> None:
        self.lock             = threading.Lock()
        self.hardware_online  = False
        self.guessed_password = ""
        self.demo_password    = DEMO_PASSWORD
        self.cap_pass_trace: Any = None


STATE = SimState()


# ---------------------------------------------------------------------------
# Trace generator
# ---------------------------------------------------------------------------

def _make_trace(guess: str) -> np.ndarray:
    """
    Return a synthetic power trace for *guess* against DEMO_PASSWORD.

    Parameters
    ----------
    guess : str
        The password attempt, optionally ending with '\\n' (SimpleSerial
        convention — stripped before comparison).

    Returns
    -------
    np.ndarray, shape (MAX_SAMPLES,), dtype float64
    """
    n     = MAX_SAMPLES
    clean = guess.rstrip("\n")

    # Seed the RNG from the guess bytes so the same guess always produces
    # the same trace.  We use only the first 8 bytes to keep the seed in
    # uint64 range without overflow.
    seed_bytes = clean.encode()[:8].ljust(8, b"\x00")
    seed = int.from_bytes(seed_bytes, "little") & 0xFFFF_FFFF
    rng  = np.random.default_rng(seed)

    trace = rng.normal(0.0, _NOISE_STD, n)

    # Power-supply ripple — identical across all guesses, so it cancels out
    # when difference traces are computed (Step 4 / api_diff).
    t = np.linspace(0.0, 1.0, n)
    trace += _RIPPLE_AMP * np.sin(2.0 * np.pi * _RIPPLE_FREQ * t)
    trace += (_RIPPLE_AMP * 0.4) * np.sin(2.0 * np.pi * _RIPPLE_FREQ * 3.7 * t)

    # Add a power spike for each correctly matched character.
    # The spike is centred at (pos+1) * _SAMPLES_PER_CHAR — one full iteration
    # worth of ADC samples after the start of the trace.
    # We stop at the first mismatch (early-exit model).
    password = STATE.demo_password
    sigma = _SPIKE_HALF_WIDTH / 2.5
    idx   = np.arange(n, dtype=float)
    for pos, ch in enumerate(clean):
        if pos >= len(password):
            break
        if ch == password[pos]:
            center = int((pos + 1) * _SAMPLES_PER_CHAR)
            if center >= n:
                break
            trace += _SPIKE_AMP * np.exp(-0.5 * ((idx - center) / sigma) ** 2)
        else:
            break  # firmware exits; no further comparison work

    return trace.astype(np.float64)


def _cap_pass_trace(pass_guess: str) -> np.ndarray:
    return _make_trace(pass_guess)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _json_error(message: str, status: int = 400):
    return jsonify({"ok": False, "message": message}), status


def _plot_to_json(fig: go.Figure) -> str:
    fig.update_layout(template="plotly_dark", paper_bgcolor="#0f172a", plot_bgcolor="#0b1220")
    return fig.to_json()


def _sim_required() -> str | None:
    if not callable(STATE.cap_pass_trace):
        return "Initialize simulation first (Step 1)."
    return None


def _capture_for_guess(guess: str) -> np.ndarray:
    return STATE.cap_pass_trace(guess + "\n")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return render_template(
        "index.html",
        scope_type=SCOPETYPE,
        platform=PLATFORM,
        ss_ver=SS_VER,
        max_samples=MAX_SAMPLES,
        default_samples=DEFAULT_SAMPLES,
        sim_mode=True,
        demo_pw_len=len(STATE.demo_password),
        demo_pw=STATE.demo_password,
    )


@app.post("/api/set_password")
def api_set_password():
    """
    Update the password the simulated firmware is checking against.

    Validates that the new password contains only characters from CHARSET
    and is between 1 and 8 characters long, then updates STATE.demo_password.
    All subsequent trace captures will use the new password immediately —
    no re-initialisation required.
    """
    payload = request.get_json(silent=True) or {}
    new_pw  = str(payload.get("password", "")).lower().strip()

    if not new_pw:
        return _json_error("Password cannot be empty.")
    if len(new_pw) > 8:
        return _json_error("Password must be 8 characters or fewer.")
    invalid = sorted({c for c in new_pw if c not in CHARSET})
    if invalid:
        return _json_error(
            f"Invalid characters: {', '.join(invalid)}. Use a–z and 0–9 only."
        )

    with STATE.lock:
        STATE.demo_password = new_pw

    return jsonify({
        "ok":      True,
        "message": f"Password updated to '{new_pw}'",
        "length":  len(new_pw),
    })


@app.post("/api/setup")
def api_setup():
    """
    Simulation initialisation — no USB, no make, no flashing.

    Registers the synthetic trace generator and runs a sanity capture to
    confirm MAX_SAMPLES samples are returned, then marks the simulation ready.
    All subsequent attack endpoints work identically to the hardware version.
    """
    with STATE.lock:
        log: list[str] = []
        try:
            log.append("Simulation mode — no hardware required.")
            log.append(f"Target password length: {len(DEMO_PASSWORD)} characters.")
            log.append("Trace model: early-exit comparison with Gaussian power spikes.")
            log.append(f"Noise floor: σ = {_NOISE_STD}  |  Spike amplitude: {_SPIKE_AMP}")
            log.append("Installing synthetic trace generator...")

            STATE.cap_pass_trace = _cap_pass_trace
            STATE.hardware_online = True

            test = STATE.cap_pass_trace("h\n")
            if len(test) != MAX_SAMPLES:
                raise RuntimeError(f"Expected {MAX_SAMPLES} samples, got {len(test)}")

            log.append(f"Sanity check passed — {MAX_SAMPLES} samples per capture.")
            log.append("Simulation online.  All attack steps are now available.")
            return jsonify({"ok": True, "message": "Simulation online", "log": log})
        except Exception as exc:
            STATE.hardware_online = False
            STATE.cap_pass_trace = None
            return jsonify({"ok": False, "message": str(exc), "log": log}), 500


@app.post("/api/compare")
def api_compare():
    """
    Capture and overlay two traces to confirm the side channel exists.

    Identical logic to the hardware version: one trace per character,
    plotted together so the divergence point is visible.
    """
    with STATE.lock:
        missing = _sim_required()
        if missing:
            return _json_error(missing, 400)

        payload = request.get_json(silent=True) or {}
        correct = str(payload.get("correct", "h"))[:1] or "h"
        wrong   = str(payload.get("wrong",   "0"))[:1] or "0"

        t1 = _capture_for_guess(correct)
        t2 = _capture_for_guess(wrong)

        fig = go.Figure()
        fig.add_trace(go.Scatter(y=t1, mode="lines", name=f"{correct} (correct)"))
        fig.add_trace(go.Scatter(y=t2, mode="lines", name=f"{wrong} (wrong)"))
        fig.update_layout(title="Correct vs Wrong Character")

        return jsonify({
            "ok": True,
            "message": f"Showing '{correct}' vs '{wrong}'",
            "plot_json": _plot_to_json(fig),
        })


@app.post("/api/sweep")
def api_sweep():
    """
    Sweep all 36 candidate characters and overlay every trace.

    The correct character's trace diverges from the cluster because it
    carries an extra power spike from the additional comparison iteration.
    """
    with STATE.lock:
        missing = _sim_required()
        if missing:
            return _json_error(missing, 400)

        payload = request.get_json(silent=True) or {}
        prefix  = str(payload.get("prefix", ""))
        samples = int(payload.get("samples", DEFAULT_SAMPLES))
        samples = max(200, min(MAX_SAMPLES, samples))

        fig = go.Figure()
        for ch in CHARSET:
            trace = _capture_for_guess(prefix + ch)
            fig.add_trace(go.Scatter(y=trace[:samples], mode="lines", name=ch, opacity=0.6))

        fig.update_layout(title=f"Sweep All Candidates (prefix='{prefix}', samples={samples})")
        return jsonify({
            "ok": True,
            "message": f"Sweep complete for prefix '{prefix}'",
            "plot_json": _plot_to_json(fig),
        })


@app.post("/api/diff")
def api_diff():
    """
    Subtract a 'definitely wrong' reference trace from every candidate.

    The reference uses \\x01 (ASCII SOH, not in CHARSET) as the first
    unknown character, guaranteeing the firmware rejects it immediately.
    Subtracting cancels the shared power-supply ripple and reveals the
    extra spike from each partially correct guess as a clean spike above
    the noise floor.
    """
    with STATE.lock:
        missing = _sim_required()
        if missing:
            return _json_error(missing, 400)

        payload = request.get_json(silent=True) or {}
        prefix  = str(payload.get("prefix", "h0p"))
        samples = int(payload.get("samples", DEFAULT_SAMPLES))
        samples = max(200, min(MAX_SAMPLES, samples))

        ref = _capture_for_guess(prefix + "\x01")[:samples]
        fig = go.Figure()

        for ch in CHARSET:
            trace = _capture_for_guess(prefix + ch)[:samples]
            diff  = trace - ref
            fig.add_trace(go.Scatter(y=diff, mode="lines", name=ch, opacity=0.6))

        fig.update_layout(title=f"Difference Traces (prefix='{prefix}')")
        return jsonify({
            "ok": True,
            "message": f"Difference traces computed for prefix '{prefix}'",
            "plot_json": _plot_to_json(fig),
        })


@app.post("/api/quant")
def api_quant():
    """
    Score every candidate character with SAD (Sum of Absolute Differences).

    SAD(c) = Σ |trace(prefix+c)[i] − reference[i]|  for all sample points i

    The character with the highest SAD score deviated most from the 'always
    wrong' reference, meaning it caused the most extra comparison work inside
    the firmware — i.e., it is correct at the current position.
    """
    with STATE.lock:
        missing = _sim_required()
        if missing:
            return _json_error(missing, 400)

        payload = request.get_json(silent=True) or {}
        prefix  = str(payload.get("prefix", "h0p"))

        ref    = _capture_for_guess(prefix + "\x01")
        scores: dict[str, float] = {}
        for ch in CHARSET:
            trace      = _capture_for_guess(prefix + ch)
            scores[ch] = float(np.sum(np.abs(trace - ref)))

        winner = max(scores, key=scores.get)

        fig = go.Figure(data=[go.Bar(
            x=list(scores.keys()),
            y=list(scores.values()),
            marker={"color": "#f59e0b"},
            name="SAD score",
        )])
        fig.update_layout(
            title=f"SAD Scores (prefix='{prefix}')",
            xaxis_title="Character",
            yaxis_title="Score",
        )

        return jsonify({
            "ok": True,
            "message": f"Best match: '{winner}'",
            "winner": winner,
            "winner_score": round(scores[winner], 2),
            "plot_json": _plot_to_json(fig),
        })


@app.post("/api/attack")
def api_attack():
    """
    Full automated password recovery — one SAD sweep per position.

    For each position:
      1. Capture a \\x01 reference (rejected at this depth, no spike here).
      2. Sweep all 36 candidates, compute SAD vs. reference.
      3. The highest-scoring candidate is the correct character.
      4. Append it to the recovered prefix and advance to the next position.

    Total captures = length × 37  (1 reference + 36 candidates per position).
    For a 5-character password: 185 captures vs. 36^5 = 60,466,176 brute-force.
    """
    with STATE.lock:
        missing = _sim_required()
        if missing:
            return _json_error(missing, 400)

        payload = request.get_json(silent=True) or {}
        length  = int(payload.get("length", 5))
        length  = max(1, min(8, length))

        guessed = ""
        logs: list[str] = []

        for pos in range(length):
            ref       = _capture_for_guess(guessed + "\x01")
            best_char = "\x01"
            best_diff = -1.0

            for ch in CHARSET:
                trace = _capture_for_guess(guessed + ch)
                diff  = float(np.sum(np.abs(trace - ref)))
                if diff > best_diff:
                    best_diff = diff
                    best_char = ch

            guessed += best_char
            logs.append(f"pos {pos + 1}: {best_char}  (SAD delta = {best_diff:.1f})")

        STATE.guessed_password = guessed
        return jsonify({
            "ok": True,
            "message": f"Password recovered: {guessed}",
            "password": guessed,
            "log": logs,
        })


@app.get("/api/health")
def api_health():
    return jsonify({
        "ok":              True,
        "hardware_online": STATE.hardware_online,
        "platform":        PLATFORM,
        "scope_type":      SCOPETYPE,
        "ss_ver":          SS_VER,
        "sim_mode":        True,
        "demo_password":   STATE.demo_password,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
