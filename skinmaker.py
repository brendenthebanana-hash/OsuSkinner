#!/usr/bin/env python3
"""osu! Skin Maker: design an osu! skin with a live preview and export it as an .osk.

Pure Python standard library (no pip, no root). One renderer draws both the preview and the
real skin files, so what you see is what you get.

  skinmaker                       open the app window
  skinmaker --browser             open in a normal browser tab instead
  skinmaker "My Skin" --preset neon --set cursor_shape=arrow      (no window, writes My Skin.osk)
  skinmaker --list-options        show every customizable option
  skinmaker "My Skin" --config saved.json                         (build from exported settings)
"""
import argparse, colorsys, hashlib, http.server, io, json, math, os, random, re, shutil
import socketserver, struct, subprocess, sys, threading, time, urllib.parse, wave, webbrowser, zipfile, zlib

APP = "osu! Skin Maker"
DATA = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "osu-skinmaker")
LIB = os.path.join(DATA, "skins")

# ======================================================================================
#  Options: single source of truth for the UI, the CLI, the validator and the renderer
# ======================================================================================
def F(k, l, t, d, **kw): return dict(k=k, l=l, t=t, d=d, **kw)
def C(k, l, d, **kw): return F(k, l, "color", d, **kw)
def R(k, l, d, lo, hi, u="", **kw): return F(k, l, "range", d, min=lo, max=hi, u=u, **kw)
def S(k, l, d, o, **kw): return F(k, l, "select", d, o=o, **kw)
def B(k, l, d, **kw): return F(k, l, "bool", d, **kw)
def P(k, l, **kw): return F(k, l, "play", None, **kw)   # preview button, not a stored option

SCHEMA = []
def G(name, *fields): SCHEMA.append({"g": name, "f": list(fields)})

STYLES = ["rounded", "square", "dotted"]
RAINBOW = ["#ff5d5d", "#ff9f43", "#ffd93d", "#9be15d", "#2ee6a6", "#2ec4ff", "#5d8bff", "#a45dff", "#ff5dc8", "#ffffff"]

G("Global color adjust",
  R("g_hue", "Hue shift", 0, -180, 180, "°"), R("g_sat", "Saturation", 100, 0, 200, "%"),
  R("g_val", "Brightness", 100, 20, 200, "%"), R("g_contrast", "Contrast", 100, 20, 200, "%"),
  B("g_gray", "Grayscale", False), B("g_invert", "Invert colors", False),
  C("g_tint", "Tint color", "#ff8800"), R("g_tint_amount", "Tint amount", 0, 0, 100, "%"))

G("Export", B("export_1x", "Also write @1x images (bigger skin, wider compatibility)", False))

G("Hit circle: shape & fill",
  S("circle_shape", "Shape", "circle", ["circle", "hexagon", "octagon", "pentagon", "triangle", "diamond", "square", "star"]),
  R("circle_size", "Size", 100, 50, 100, "%"), R("circle_rotation", "Rotation", 0, -180, 180, "°"),
  R("circle_corner", "Square corner rounding", 30, 0, 100, "%"),
  R("circle_star_points", "Star points", 5, 3, 12), R("circle_star_inner", "Star inner radius", 50, 20, 90, "%"),
  C("circle_fill", "Fill color", "#ffffff"), C("circle_fill2", "Second fill color", "#b8b8b8"),
  S("circle_fill_mode", "Fill mode", "solid", ["solid", "radial", "linear"]),
  R("circle_grad_angle", "Gradient angle", 90, 0, 360, "°"), R("circle_fill_alpha", "Fill opacity", 100, 0, 100, "%"),
  S("circle_pattern", "Pattern", "none", ["none", "stripes", "dots", "checker", "rings"]),
  C("circle_pattern_color", "Pattern color", "#000000"), R("circle_pattern_alpha", "Pattern opacity", 20, 0, 100, "%"),
  R("circle_pattern_scale", "Pattern size", 24, 6, 80, "px"), R("circle_pattern_angle", "Pattern angle", 45, 0, 180, "°"),
  B("circle_shine", "Glossy highlight", False), R("circle_shine_alpha", "Highlight strength", 35, 0, 100, "%"),
  B("circle_shadow", "Drop shadow", False), R("circle_shadow_alpha", "Shadow opacity", 50, 0, 100, "%"),
  R("circle_shadow_offset", "Shadow offset", 6, 0, 20, "px"))

G("Hit circle: outline & glow",
  C("circle_outline", "Outline color", "#ffffff"), R("circle_outline_w", "Outline width", 12, 0, 30, "px"),
  S("circle_outline_style", "Outline style", "solid", ["solid", "dashed", "dotted", "double"]),
  R("circle_outline_alpha", "Outline opacity", 100, 0, 100, "%"), R("circle_dash_count", "Dash count", 16, 4, 48),
  B("circle_inner_on", "Inner ring", False), C("circle_inner_color", "Inner ring color", "#ffffff"),
  R("circle_inner_w", "Inner ring width", 4, 1, 16, "px"), R("circle_inner_gap", "Inner ring gap", 22, 4, 60, "px"),
  B("circle_glow", "Outer glow", False), C("circle_glow_color", "Glow color", "#ffffff"),
  R("circle_glow_size", "Glow size", 12, 2, 40, "px"), R("circle_glow_alpha", "Glow opacity", 60, 0, 100, "%"))

G("Hit circle numbers",
  S("number_style", "Style", "rounded", STYLES), C("number_color", "Color", "#ffffff"),
  B("number_gradient", "Vertical gradient", False), C("number_color2", "Gradient end color", "#9be1ff"),
  R("number_weight", "Thickness", 10, 4, 20, "px"), R("number_size", "Size", 100, 50, 140, "%"),
  R("number_slant", "Slant", 0, -25, 25, "°"), R("number_alpha", "Opacity", 100, 10, 100, "%"),
  R("number_offset_y", "Vertical offset", 0, -20, 20, "px"),
  B("number_outline", "Outline", False), C("number_outline_color", "Outline color", "#000000"),
  R("number_outline_w", "Outline width", 4, 1, 10, "px"),
  B("number_glow", "Glow", False), C("number_glow_color", "Glow color", "#ffffff"), R("number_glow_size", "Glow size", 10, 2, 30, "px"),
  B("number_shadow", "Drop shadow", False), R("number_overlap", "Spacing (overlap)", 6, -20, 30, "px"),
  B("number_per_digit", "Different color per digit", False),
  *[C(f"number_d{i}", f"Digit {i} color", RAINBOW[i]) for i in range(10)])

G("Approach circle",
  S("approach_style", "Style", "ring", ["ring", "double", "dashed", "dotted", "glow"]),
  S("approach_shape", "Shape", "circle", ["circle", "match"]),
  C("approach_color", "Color", "#ffffff"), R("approach_w", "Thickness", 8, 2, 20, "px"),
  R("approach_alpha", "Opacity", 100, 10, 100, "%"), R("approach_radius", "Radius", 100, 70, 100, "%"),
  R("approach_dash_count", "Dash count", 24, 6, 60), R("approach_gap", "Double ring gap", 12, 4, 30, "px"),
  R("approach_fill", "Inner fill opacity", 0, 0, 60, "%"))

G("Cursor",
  S("cursor_shape", "Shape", "ring", ["ring", "dot", "cross", "crosshair", "diamond", "square", "star", "arrow"]),
  R("cursor_size", "Size", 52, 24, 70), R("cursor_weight", "Thickness", 10, 3, 18, "px"),
  R("cursor_angle", "Rotation", 0, -180, 180, "°"), C("cursor_color", "Color", "#ffffff"),
  C("cursor_color2", "Center / fill color", "#ffffff"), R("cursor_dot", "Center dot size", 9, 0, 22, "px"),
  R("cursor_fill_alpha", "Inner fill opacity", 0, 0, 100, "%"), R("cursor_alpha", "Overall opacity", 100, 20, 100, "%"),
  B("cursor_outline", "Outline", False), C("cursor_outline_color", "Outline color", "#000000"),
  R("cursor_outline_w", "Outline width", 4, 1, 10, "px"), R("cursor_outline_alpha", "Outline opacity", 80, 0, 100, "%"),
  B("cursor_glow", "Glow", False), C("cursor_glow_color", "Glow color", "#ffffff"), R("cursor_glow_size", "Glow size", 14, 3, 30, "px"),
  B("cursor_shadow", "Drop shadow", False), R("cursor_shadow_alpha", "Shadow opacity", 50, 0, 100, "%"),
  B("cursor_middle", "Separate center dot image (cursormiddle)", False))

G("Cursor trail",
  S("trail_style", "Style", "glow", ["glow", "dot", "ring", "star", "none"]),
  C("trail_color", "Color", "#ffffff"), C("trail_color2", "Outer color (glow)", "#ffffff"),
  R("trail_size", "Size", 28, 6, 30), R("trail_alpha", "Opacity", 100, 10, 100, "%"),
  R("trail_weight", "Ring thickness", 5, 2, 12, "px"), R("trail_inner", "Glow core size", 40, 10, 90, "%"))

G("Slider ball",
  S("ball_style", "Style", "ring", ["ring", "disc", "glow", "diamond", "none"]),
  C("ball_color", "Color", "#ffffff"), C("ball_color2", "Inner fill color", "#ffffff"),
  R("ball_size", "Size", 100, 40, 100, "%"), R("ball_ring_w", "Ring width", 12, 0, 24, "px"),
  R("ball_fill_alpha", "Inner fill opacity", 27, 0, 100, "%"), R("ball_alpha", "Overall opacity", 100, 10, 100, "%"),
  B("ball_glow", "Glow", False), R("ball_glow_size", "Glow size", 10, 2, 30, "px"))

G("Follow circle",
  S("follow_style", "Style", "ring", ["ring", "glow", "dashed", "none"]),
  C("follow_color", "Color", "#ffffff"), R("follow_size", "Size", 100, 50, 100, "%"),
  R("follow_w", "Thickness", 8, 2, 20, "px"), R("follow_alpha", "Opacity", 67, 10, 100, "%"),
  R("follow_dash", "Dash count", 24, 6, 60), R("follow_glow_size", "Glow size", 16, 4, 40, "px"))

G("Reverse arrow",
  S("arrow_style", "Style", "chevron", ["chevron", "arrow", "triangle"]),
  C("arrow_color", "Color", "#ffffff"), R("arrow_size", "Size", 70, 20, 100, "%"),
  R("arrow_weight", "Thickness", 12, 4, 24, "px"), R("arrow_alpha", "Opacity", 100, 10, 100, "%"),
  B("arrow_flip", "Flip direction", False))

G("Slider ticks",
  S("tick_style", "Style", "disc", ["disc", "ring", "diamond"]),
  C("tick_color", "Color", "#ffffff"), R("tick_size", "Size", 8, 3, 20, "px"), R("tick_alpha", "Opacity", 100, 10, 100, "%"))

G("Follow points",
  S("fp_style", "Style", "dot", ["dot", "line", "arrow", "chevron"]),
  C("fp_color", "Color", "#ffffff"), R("fp_size", "Size", 10, 3, 24, "px"), R("fp_alpha", "Opacity", 70, 10, 100, "%"))

G("Slider body",
  C("slider_border", "Border color", "#ffffff"), B("slider_track_on", "Use a fixed track color", False),
  C("slider_track", "Track color", "#1b1b26"))

G("Hit results (300 / 100 / 50 / miss)",
  S("hit_style", "Text style", "rounded", STYLES), R("hit_weight", "Text thickness", 10, 4, 20, "px"),
  R("hit_slant", "Text slant", 0, -25, 25, "°"),
  B("hit_outline", "Outline", False), C("hit_outline_color", "Outline color", "#000000"), R("hit_outline_w", "Outline width", 4, 1, 10, "px"),
  B("hit_glow", "Glow", False), C("hit_glow_color", "Glow color", "#ffffff"), R("hit_glow_size", "Glow size", 10, 2, 30, "px"),
  B("hit_shadow", "Drop shadow", False),
  S("hit0_shape", "Miss symbol", "x", ["x", "plus", "dot", "ring", "bar"]),
  C("hit300_color", "300 color", "#4fc3ff"), R("hit300_scale", "300 size", 100, 40, 160, "%"), R("hit300_alpha", "300 opacity", 100, 10, 100, "%"),
  C("hit100_color", "100 color", "#7bff4f"), R("hit100_scale", "100 size", 100, 40, 160, "%"), R("hit100_alpha", "100 opacity", 100, 10, 100, "%"),
  C("hit50_color", "50 color", "#ffb300"), R("hit50_scale", "50 size", 100, 40, 160, "%"), R("hit50_alpha", "50 opacity", 100, 10, 100, "%"),
  C("hit0_color", "Miss color", "#ff4040"), R("hit0_scale", "Miss size", 100, 40, 160, "%"), R("hit0_alpha", "Miss opacity", 100, 10, 100, "%"))

G("Spinner",
  S("spinner_style", "Style", "ring", ["ring", "double", "dashed"]),
  C("spinner_color", "Color", "#ffffff"), R("spinner_ring_w", "Ring width", 14, 2, 40, "px"),
  R("spinner_ticks", "Tick marks", 12, 0, 48), R("spinner_tick_len", "Tick length", 28, 6, 80, "px"),
  R("spinner_fill_alpha", "Inner fill opacity", 0, 0, 60, "%"), R("spinner_alpha", "Opacity", 100, 10, 100, "%"),
  C("spinner_approach_color", "Approach ring color", "#ffffff"), R("spinner_approach_w", "Approach ring width", 8, 2, 30, "px"),
  R("spinner_approach_alpha", "Approach ring opacity", 100, 10, 100, "%"))

G("Score & combo numbers",
  S("score_style", "Style", "rounded", STYLES), C("score_color", "Color", "#ffffff"),
  B("score_gradient", "Vertical gradient", False), C("score_color2", "Gradient end color", "#9be1ff"),
  R("score_weight", "Thickness", 10, 4, 20, "px"), R("score_size", "Size", 100, 50, 140, "%"),
  R("score_slant", "Slant", 0, -25, 25, "°"), R("score_alpha", "Opacity", 100, 10, 100, "%"),
  B("score_outline", "Outline", False), C("score_outline_color", "Outline color", "#000000"), R("score_outline_w", "Outline width", 4, 1, 10, "px"),
  B("score_glow", "Glow", False), C("score_glow_color", "Glow color", "#ffffff"), R("score_glow_size", "Glow size", 10, 2, 30, "px"),
  B("score_shadow", "Drop shadow", False),
  R("score_overlap", "Score spacing (overlap)", 4, -20, 30, "px"), R("combo_overlap", "Combo spacing (overlap)", 4, -20, 30, "px"),
  B("score_per_digit", "Different color per digit", False),
  *[C(f"score_d{i}", f"Digit {i} color", RAINBOW[i]) for i in range(10)])

SAMPLES = [  # name, label, defaults
    ("hitnormal", "Hit normal", dict(wave="sine", freq=190, sweep=70, decay=110, attack=1, noise=12, harm=25, drive=15, lowpass=5000, crush=16, tremolo=0, vibrato=0, echo=0, echo_ms=90, volume=85)),
    ("hitclap", "Hit clap", dict(wave="noise", freq=1500, sweep=900, decay=130, attack=2, noise=100, harm=0, drive=10, lowpass=7000, crush=16, tremolo=0, vibrato=0, echo=18, echo_ms=22, volume=75)),
    ("hitwhistle", "Hit whistle", dict(wave="sine", freq=1900, sweep=1750, decay=260, attack=8, noise=4, harm=10, drive=0, lowpass=9000, crush=16, tremolo=6, vibrato=3, echo=0, echo_ms=90, volume=60)),
    ("hitfinish", "Hit finish (cymbal)", dict(wave="noise", freq=3000, sweep=2200, decay=700, attack=2, noise=100, harm=0, drive=5, lowpass=12000, crush=16, tremolo=0, vibrato=0, echo=15, echo_ms=45, volume=60)),
    ("slidertick", "Slider tick", dict(wave="triangle", freq=1300, sweep=1100, decay=45, attack=1, noise=0, harm=0, drive=0, lowpass=9000, crush=16, tremolo=0, vibrato=0, echo=0, echo_ms=90, volume=55)),
    ("combobreak", "Combo break", dict(wave="saw", freq=420, sweep=90, decay=380, attack=2, noise=8, harm=0, drive=30, lowpass=2500, crush=12, tremolo=0, vibrato=0, echo=0, echo_ms=90, volume=70)),
    ("sliderslide", "Slider slide (loop)", dict(wave="triangle", freq=180, sweep=180, decay=800, attack=5, noise=10, harm=30, drive=10, lowpass=3000, crush=16, tremolo=7, vibrato=0, echo=0, echo_ms=90, volume=40)),
    ("sliderwhistle", "Slider whistle (loop)", dict(wave="sine", freq=1500, sweep=1500, decay=800, attack=5, noise=3, harm=10, drive=0, lowpass=8000, crush=16, tremolo=5, vibrato=4, echo=0, echo_ms=90, volume=35)),
]
LOOPS = ("sliderslide", "sliderwhistle")
WAVES = ["sine", "square", "saw", "triangle", "noise"]

G("Sound: general",
  B("sound_enabled", "Generate hit sounds", True), R("sound_master", "Master volume", 90, 10, 100, "%"),
  B("sound_normal", "Write normal- set", True), B("sound_soft", "Write soft- set (higher pitch, quieter)", True),
  B("sound_drum", "Write drum- set (lower pitch)", True),
  R("soft_pitch", "Soft set pitch", 120, 50, 200, "%"), R("drum_pitch", "Drum set pitch", 80, 50, 200, "%"),
  R("soft_volume", "Soft set volume", 70, 10, 100, "%"), R("drum_volume", "Drum set volume", 100, 10, 100, "%"))

for _n, _l, _d in SAMPLES:
    G(f"Sound: {_l}",
      P(f"play_{_n}", "Preview"),
      S(f"sn_{_n}_wave", "Waveform", _d["wave"], WAVES),
      R(f"sn_{_n}_freq", "Start pitch", _d["freq"], 40, 8000, "Hz"), R(f"sn_{_n}_sweep", "End pitch", _d["sweep"], 40, 8000, "Hz"),
      R(f"sn_{_n}_attack", "Attack", _d["attack"], 0, 100, "ms"), R(f"sn_{_n}_decay", "Loop length" if _n in LOOPS else "Decay", _d["decay"], 10, 1500, "ms"),
      R(f"sn_{_n}_noise", "Noise mix", _d["noise"], 0, 100, "%"), R(f"sn_{_n}_harm", "2nd harmonic", _d["harm"], 0, 100, "%"),
      R(f"sn_{_n}_drive", "Distortion", _d["drive"], 0, 100, "%"), R(f"sn_{_n}_lowpass", "Low-pass cutoff", _d["lowpass"], 300, 16000, "Hz"),
      R(f"sn_{_n}_crush", "Bit depth", _d["crush"], 4, 16, "bit"), R(f"sn_{_n}_tremolo", "Tremolo", _d["tremolo"], 0, 40, "Hz"),
      R(f"sn_{_n}_vibrato", "Vibrato", _d["vibrato"], 0, 40, "Hz"), R(f"sn_{_n}_echo", "Echo amount", _d["echo"], 0, 80, "%"),
      R(f"sn_{_n}_echo_ms", "Echo delay", _d["echo_ms"], 5, 300, "ms"), R(f"sn_{_n}_volume", "Volume", _d["volume"], 5, 100, "%"))

G("skin.ini: behavior",
  S("ini_version", "Skin version", "2.5", ["latest", "2.5", "2.2", "2.0", "1.0"]),
  B("cursor_rotate", "Cursor rotates while moving", False), B("cursor_expand", "Cursor grows on click", True),
  S("cursor_centre", "Cursor hotspot", "auto", ["auto", "centre", "top-left"]),
  B("slider_ball_flip", "Flip slider ball on repeat", False), B("allow_slider_ball_tint", "Tint slider ball with combo color", True),
  B("overlay_above_number", "Circle outline above numbers", True), B("spinner_no_blink", "Spinner meter doesn't blink", False),
  B("spinner_fade_playfield", "Spinner fades the playfield", False), B("spinner_freq_mod", "Spinner sound pitch follows speed", True),
  B("layered_hitsounds", "Layered hit sounds", True), B("combo_burst_random", "Random combo bursts", False),
  B("samples_match_rate", "Samples match playback rate", False), R("animation_fps", "Animation framerate (0 = default)", 0, 0, 60, "fps"))

G("skin.ini: menu & UI colors",
  C("ini_spinner_bg", "Spinner background", "#646464"), C("ini_input_text", "Input overlay text", "#000000"),
  C("ini_menu_glow", "Menu glow", "#004e9b"), C("ini_select_active", "Song select active text", "#000000"),
  C("ini_select_inactive", "Song select inactive text", "#ffffff"), C("ini_star_break", "Star break additive", "#ffb6c1"))

PRESETS = {
    "classic": {"combos": ["#ffc000", "#00ca00", "#127cff", "#f21839"]},
    "neon": {"combos": ["#ff2e88", "#2ee6ff", "#b6ff2e", "#ffd02e"], "circle_outline": "#ff2e88", "circle_glow": True,
             "circle_glow_color": "#ff2e88", "cursor_color": "#2ee6ff", "cursor_color2": "#ff2e88", "cursor_glow": True,
             "cursor_glow_color": "#2ee6ff", "trail_color": "#2ee6ff", "trail_color2": "#2ee6ff", "ball_color": "#2ee6ff",
             "ball_glow": True, "slider_border": "#ff2e88", "number_glow": True, "number_glow_color": "#ff2e88"},
    "pastel": {"combos": ["#ffb3c7", "#b3d9ff", "#c9ffb3", "#fff0b3"], "circle_fill_mode": "radial", "circle_fill2": "#ffe6ee",
               "circle_shine": True, "circle_outline": "#ffffff", "cursor_color": "#ffb3c7", "cursor_color2": "#b3d9ff",
               "trail_color": "#ffb3c7", "ball_color": "#b3d9ff", "number_color": "#ffffff", "number_outline": True,
               "number_outline_color": "#e58fa9"},
    "dark": {"combos": ["#8a5cff", "#00c2a8", "#ff6b6b", "#ffa94d"], "circle_fill_mode": "radial", "circle_fill": "#ffffff",
             "circle_fill2": "#8c8caa", "circle_outline": "#d9d9ff", "cursor_shape": "diamond", "cursor_color": "#d9d9ff",
             "trail_color": "#8a5cff", "slider_border": "#d9d9ff", "slider_track_on": True, "slider_track": "#15121f"},
    "sunset": {"combos": ["#ff7e5f", "#feb47b", "#ff4f81", "#ffd166"], "circle_outline": "#fff1e6", "cursor_shape": "arrow",
               "cursor_color": "#fff1e6", "cursor_outline": True, "trail_style": "dot", "trail_color": "#ff7e5f",
               "ball_color": "#ffd166", "slider_border": "#fff1e6", "circle_shine": True},
    "mono": {"combos": ["#ffffff", "#c8c8c8", "#9a9a9a", "#6e6e6e"], "circle_fill_alpha": 15, "circle_outline_w": 8,
             "cursor_shape": "cross", "cursor_weight": 6, "trail_style": "none", "slider_border": "#ffffff"},
    "retro": {"combos": ["#ff004d", "#ffec27", "#00e436", "#29adff"], "circle_shape": "square", "circle_corner": 20,
              "circle_outline_style": "double", "number_style": "square", "score_style": "square", "hit_style": "square",
              "cursor_shape": "square", "trail_style": "dot", "approach_style": "dashed", "approach_shape": "match"},
    "candy": {"combos": ["#ff6fb5", "#6fd6ff", "#ffe56f", "#9d6fff"], "circle_pattern": "stripes", "circle_pattern_alpha": 28,
              "circle_pattern_color": "#ffffff", "circle_shine": True, "circle_outline_w": 10, "number_style": "rounded",
              "number_outline": True, "number_outline_color": "#7a2a5a", "cursor_shape": "star", "trail_style": "star"},
    "hex": {"combos": ["#00f5d4", "#f15bb5", "#fee440", "#9b5de5"], "circle_shape": "hexagon", "circle_outline_w": 10,
            "circle_inner_on": True, "approach_shape": "match", "cursor_shape": "crosshair", "number_style": "dotted",
            "ball_style": "diamond", "tick_style": "diamond"},
}

DEFAULTS = {"name": "My Skin", "author": "", "combos": list(PRESETS["classic"]["combos"])}
for _g in SCHEMA:
    for _f in _g["f"]:
        if _f["t"] != "play": DEFAULTS[_f["k"]] = _f["d"]
for _n, _l, _d in SAMPLES: pass
COLOR_KEYS = [f["k"] for g in SCHEMA for f in g["f"] if f["t"] == "color" and f["k"] != "g_tint"]
NOPT = sum(1 for g in SCHEMA for f in g["f"] if f["t"] != "play") + 8   # + the 8 combo color slots

def hexrgb(s):
    s = str(s).strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", s):
        raise ValueError(f"bad color '{s}' (use 6 digit hex like ff2e88)")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))

def hexstr(rgb): return "#%02x%02x%02x" % tuple(rgb)

def norm(cfg):
    """Validate and clamp a config. Unknown or bad values fall back to defaults."""
    out = json.loads(json.dumps(DEFAULTS))
    cfg = cfg or {}
    for g in SCHEMA:
        for f in g["f"]:
            t, k = f["t"], f["k"]
            if t == "play": continue
            v = cfg.get(k, f["d"])
            try:
                if t == "color": v = hexstr(hexrgb(v))
                elif t == "range": v = max(f["min"], min(f["max"], int(round(float(v)))))
                elif t == "select": v = v if v in f["o"] else f["d"]
                elif t == "bool": v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
            except (ValueError, TypeError):
                v = f["d"]
            out[k] = v
    combos = []
    for c in (cfg.get("combos") or []):
        try: combos.append(hexstr(hexrgb(c)))
        except ValueError: pass
    out["combos"] = combos[:8] or out["combos"]
    out["name"] = str(cfg.get("name") or DEFAULTS["name"])[:60]
    out["author"] = str(cfg.get("author") or "")[:60]
    return out

def effective(c):
    """Apply the global color adjustments to every color."""
    c = json.loads(json.dumps(c))
    tint = hexrgb(c["g_tint"]); amt = c["g_tint_amount"] / 100
    def adj(hx):
        r, g, b = [v / 255 for v in hexrgb(hx)]
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        h = (h + c["g_hue"] / 360) % 1
        s = min(1.0, s * c["g_sat"] / 100); v = min(1.0, v * c["g_val"] / 100)
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        k = c["g_contrast"] / 100
        r, g, b = [(x - .5) * k + .5 for x in (r, g, b)]
        if c["g_gray"]: r = g = b = .299 * r + .587 * g + .114 * b
        if c["g_invert"]: r, g, b = 1 - r, 1 - g, 1 - b
        if amt: r, g, b = [x * (1 - amt) + (t / 255) * amt for x, t in zip((r, g, b), tint)]
        return hexstr([int(max(0, min(1, x)) * 255 + .5) for x in (r, g, b)])
    for k in COLOR_KEYS: c[k] = adj(c[k])
    c["combos"] = [adj(x) for x in c["combos"]]
    return c

# ======================================================================================
#  Rasterizer.  A layer is (shape_fn, color, bbox); shape_fn(x, y, e) -> coverage 0..1,
#  where e = output pixels per design unit.  color is (r,g,b,a) or a function (x,y)->(r,g,b,a).
#  Shapes are built from signed distance functions: an "sd" is (fn(x,y)->distance, bbox).
#  Everything is designed in @2x units.
# ======================================================================================
M = 4
def pad(bb, p): return (bb[0] - p, bb[1] - p, bb[2] + p, bb[3] + p)
def pct(v): return int(round(v * 2.55))
def clamp(v, lo=0.0, hi=1.0): return lo if v < lo else hi if v > hi else v
def mix(a, b, t): return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))
def cov(d): return 0.0 if d > 0.5 else 1.0 if d < -0.5 else 0.5 - d
def rgba(hx, a=255): return hexrgb(hx) + (a,)

def sd_circle(cx, cy, r):
    return (lambda x, y: math.hypot(x - cx, y - cy) - r, (cx - r, cy - r, cx + r, cy + r))

def sd_seg(x1, y1, x2, y2, w):
    dx, dy = x2 - x1, y2 - y1
    L = dx * dx + dy * dy
    def f(x, y):
        t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / L)) if L else 0.0
        return math.hypot(x - x1 - t * dx, y - y1 - t * dy) - w / 2
    h = w / 2
    return (f, (min(x1, x2) - h, min(y1, y2) - h, max(x1, x2) + h, max(y1, y2) + h))

def sd_box(x0, y0, x1, y1, r=0.0):
    cx, cy, hx, hy = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2 - r, (y1 - y0) / 2 - r
    def f(x, y):
        qx, qy = abs(x - cx) - hx, abs(y - cy) - hy
        return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - r
    return (f, (x0, y0, x1, y1))

def sd_poly(pts):
    n = len(pts)
    def f(x, y):
        best, inside = 1e9, False
        for i in range(n):
            ax, ay = pts[i]; bx, by = pts[(i + 1) % n]
            if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
                inside = not inside
            dx, dy = bx - ax, by - ay
            L = dx * dx + dy * dy
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L)) if L else 0.0
            d = math.hypot(x - ax - t * dx, y - ay - t * dy)
            if d < best: best = d
        return -best if inside else best
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (f, (min(xs), min(ys), max(xs), max(ys)))

def ngon(cx, cy, r, n, rot=-90):
    return [(cx + r * math.cos(math.radians(rot + 360.0 * i / n)), cy + r * math.sin(math.radians(rot + 360.0 * i / n))) for i in range(n)]

def star_pts(cx, cy, r, n, inner, rot=-90):
    return [(cx + (r if i % 2 == 0 else r * inner) * math.cos(math.radians(rot + 180.0 * i / n)),
             cy + (r if i % 2 == 0 else r * inner) * math.sin(math.radians(rot + 180.0 * i / n))) for i in range(2 * n)]

def sd_union(sds):
    if len(sds) == 1: return sds[0]
    fns = [s[0] for s in sds]
    bb = (min(s[1][0] for s in sds), min(s[1][1] for s in sds), max(s[1][2] for s in sds), max(s[1][3] for s in sds))
    return (lambda x, y: min(f(x, y) for f in fns), bb)

def sd_stroke(sd, w): f, bb = sd; return (lambda x, y: abs(f(x, y)) - w / 2, pad(bb, w / 2))
def sd_grow(sd, g): f, bb = sd; return (lambda x, y: f(x, y) - g, pad(bb, max(g, 0)))
def sd_shift(sd, dx, dy):
    f, bb = sd
    return (lambda x, y: f(x - dx, y - dy), (bb[0] + dx, bb[1] + dy, bb[2] + dx, bb[3] + dy))

def sd_shear(sd, py, k):
    f, bb = sd
    ext = abs(k) * max(abs(bb[1] - py), abs(bb[3] - py))
    return (lambda x, y: f(x - (py - y) * k, y), (bb[0] - ext, bb[1], bb[2] + ext, bb[3]))

def sd_rot(sd, cx, cy, deg):
    f, bb = sd
    a = math.radians(deg); ca, sa = math.cos(a), math.sin(a)
    R = max(math.hypot(x - cx, y - cy) for x in (bb[0], bb[2]) for y in (bb[1], bb[3]))
    return (lambda x, y: f(cx + (x - cx) * ca + (y - cy) * sa, cy - (x - cx) * sa + (y - cy) * ca),
            (cx - R, cy - R, cx + R, cy + R))

def L_fill(sd, col): f, bb = sd; return (lambda x, y, e: cov(f(x, y) * e), col, pad(bb, M))
def L_stroke(sd, w, col, off):  # stroke of width w inside the shape edge (off = w/2) or centered (off = 0)
    f, bb = sd
    return (lambda x, y, e: cov((abs(f(x, y) + off) - w / 2) * e), col, pad(bb, M))
def L_glow(sd, g, col):  # soft halo outside the shape
    f, bb = sd
    def fn(x, y, e):
        d = f(x, y)
        return 0.0 if d <= 0 or d >= g else (1 - d / g) ** 2
    return (fn, col, pad(bb, g + M))
def masked(layer, mask): fn, col, bb = layer; return (lambda x, y, e: fn(x, y, e) * mask(x, y), col, bb)

def dash_mask(cx, cy, n, duty, r):
    per = 2 * math.pi * max(r, 1.0) / n
    def m(x, y):
        t = (math.atan2(y - cy, x - cx) / (2 * math.pi) * n) % 1.0
        d = min(t, duty - t) * per if t < duty else -min(t - duty, 1 - t) * per
        return clamp(d * 0.7 + 0.5)
    return m

def mapcol(layers, g):
    return [(fn, (lambda c: lambda x, y: g(c(x, y)))(col) if callable(col) else g(col), bb) for fn, col, bb in layers]
def tint(layers, rgb): return mapcol(layers, lambda c: (c[0] * rgb[0] // 255, c[1] * rgb[1] // 255, c[2] * rgb[2] // 255, c[3]))
def fade(layers, a): return mapcol(layers, lambda c: (c[0], c[1], c[2], int(c[3] * a))) if a < 1 else layers

def place(layers, dx, dy, k=1.0):
    out = []
    for fn, col, (x0, y0, x1, y1) in layers:
        f = (lambda fn: lambda x, y, e: fn((x - dx) / k, (y - dy) / k, e * k))(fn)
        c = (lambda col: lambda x, y: col((x - dx) / k, (y - dy) / k))(col) if callable(col) else col
        out.append((f, c, (x0 * k + dx, y0 * k + dy, x1 * k + dx, y1 * k + dy)))
    return out

def put(layers, cx, cy, w, h, k=1.0, rot=0.0):
    """Centre a w x h sprite on (cx,cy), scaled by k and rotated by rot degrees."""
    if not rot: return place(layers, cx - w * k / 2, cy - h * k / 2, k)
    a = math.radians(rot); ca, sa = math.cos(a), math.sin(a)
    inv = lambda x, y: (((x - cx) / k) * ca + ((y - cy) / k) * sa + w / 2, -((x - cx) / k) * sa + ((y - cy) / k) * ca + h / 2)
    Rr = math.hypot(w, h) / 2 * k
    out = []
    for fn, col, bb in layers:
        f = (lambda fn: lambda x, y, e: fn(*inv(x, y), e * k))(fn)
        c = (lambda col: lambda x, y: col(*inv(x, y)))(col) if callable(col) else col
        out.append((f, c, (cx - Rr, cy - Rr, cx + Rr, cy + Rr)))
    return out

def png_bytes(w, h, rows):
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b""))

def render(w, h, layers, scale=1.0, bg=None):
    w, h = max(1, int(w)), max(1, int(h))
    n = w * h
    if bg: R, G, B, A = [float(bg[0])] * n, [float(bg[1])] * n, [float(bg[2])] * n, [1.0] * n
    else: R, G, B, A = [0.0] * n, [0.0] * n, [0.0] * n, [0.0] * n
    for fn, col, (x0, y0, x1, y1) in layers:
        px0, px1 = max(0, int(math.floor(x0 * scale))), min(w, int(math.ceil(x1 * scale)))
        py0, py1 = max(0, int(math.floor(y0 * scale))), min(h, int(math.ceil(y1 * scale)))
        dyn = callable(col)
        for py in range(py0, py1):
            y = (py + 0.5) / scale
            base = py * w
            for px in range(px0, px1):
                x = (px + 0.5) / scale
                k = fn(x, y, scale)
                if k <= 0: continue
                c = col(x, y) if dyn else col
                ca = k * c[3] / 255
                if ca <= 0: continue
                i, ia = base + px, 1 - ca
                R[i] = c[0] * ca + R[i] * ia; G[i] = c[1] * ca + G[i] * ia
                B[i] = c[2] * ca + B[i] * ia; A[i] = ca + A[i] * ia
    raw = bytearray()
    for py in range(h):
        raw.append(0)
        for i in range(py * w, py * w + w):
            a = A[i]
            if a > 0:
                raw += bytes((min(255, int(R[i] / a + .5)), min(255, int(G[i] / a + .5)),
                              min(255, int(B[i] / a + .5)), int(a * 255 + .5)))
            else:
                raw += b"\0\0\0\0"
    return png_bytes(w, h, bytes(raw))

# ======================================================================================
#  Glyphs (numbers, score font, hit results)
# ======================================================================================
CR = 118
SEGS = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc",
        "5": "afgcd", "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg"}
DW, DH, GAP = 56, 88, 6
TRANSPARENT = (1, 1, [])

def glyph(ch, style, T, x0):
    if ch in SEGS:
        m = T / 2 + 1
        xl, xr, yt, ym, yb = x0 + m, x0 + DW - m, m, DH / 2, DH - m
        P = {"a": (xl, yt, xr, yt), "b": (xr, yt, xr, ym), "c": (xr, ym, xr, yb), "d": (xl, yb, xr, yb),
             "e": (xl, ym, xl, yb), "f": (xl, yt, xl, ym), "g": (xl, ym, xr, ym)}
        segs = [(x0 + DW / 2, yt, x0 + DW / 2, yb)] if ch == "1" else [P[s] for s in SEGS[ch]]
        parts = []
        for a, b, c2, d in segs:
            if style == "rounded": parts.append(sd_seg(a, b, c2, d, T))
            elif style == "square": parts.append(sd_box(min(a, c2) - T / 2, min(b, d) - T / 2, max(a, c2) + T / 2, max(b, d) + T / 2))
            else:
                n = max(2, int(math.hypot(c2 - a, d - b) / (T * 1.7)) + 1)
                parts += [sd_circle(a + (c2 - a) * i / (n - 1), b + (d - b) * i / (n - 1), T * 0.55) for i in range(n)]
        return sd_union(parts), DW
    if ch == ".":
        return sd_circle(x0 + 13, DH - T * 0.9, T * 0.75), 26
    if ch == ",":
        return sd_union([sd_circle(x0 + 13, DH - T * 1.1, T * 0.7), sd_seg(x0 + 13, DH - T * 1.1, x0 + 7, DH + 6, T * 0.7)]), 26
    if ch == "%":
        t = T * 0.7
        return sd_union([sd_stroke(sd_circle(x0 + 15, 26, 12), t), sd_stroke(sd_circle(x0 + 49, DH - 26, 12), t),
                         sd_seg(x0 + 52, 10, x0 + 12, DH - 10, t)]), 64
    return sd_union([sd_seg(x0 + 10, 34, x0 + 38, DH - 12, T), sd_seg(x0 + 38, 34, x0 + 10, DH - 12, T)]), 48   # "x"

def text_sd(s, style, T, slant):
    x, parts = 0, []
    for ch in s:
        sd, w = glyph(ch, style, T, x)
        parts.append(sd); x += w + GAP
    u = sd_union(parts)
    k = math.tan(math.radians(slant))
    return (sd_shear(u, DH / 2, k) if k else u), x - GAP

def deco(sd, col, shadow=0, glow=None, outline=None):
    L = []
    if shadow: L.append(L_fill(sd_shift(sd, 3, 4), (0, 0, 0, shadow)))
    if glow: L.append(L_glow(sd, glow[0], glow[1]))
    if outline: L.append(L_fill(sd_grow(sd, outline[0]), outline[1]))
    L.append(L_fill(sd, col))
    return L

def text_sprite(s, o, color=None):
    k = o["size"] / 100.0
    sd, wid = text_sd(s, o["style"], o["T"], o["slant"])
    extra = max(o["ow"] if o["outline"] else 0, o["gsize"] if o["glow"] else 0, 3) + 6
    padx = extra + abs(math.tan(math.radians(o["slant"]))) * DH / 2
    offy = o.get("offy", 0)
    pady = extra + 8 + abs(offy)
    base = hexrgb(color or o["color"])
    if o["gradient"] and not color:
        c1, c2 = base, hexrgb(o["color2"])
        col = lambda x, y: mix(c1, c2, clamp(y / DH)) + (255,)
    else:
        col = base + (255,)
    L = deco(sd, col, 150 if o["shadow"] else 0,
             (o["gsize"], rgba(o["gcolor"], 170)) if o["glow"] else None,
             (o["ow"], rgba(o["ocolor"])) if o["outline"] else None)
    L = fade(L, o["alpha"] / 100.0)
    return ((wid + 2 * padx) * k, (DH + 2 * pady) * k, place(L, padx * k, (pady + offy) * k, k))

def num_opts(c, p):
    return dict(style=c[p + "_style"], T=c[p + "_weight"], slant=c[p + "_slant"], color=c[p + "_color"],
                color2=c[p + "_color2"], gradient=c[p + "_gradient"], size=c[p + "_size"], alpha=c[p + "_alpha"],
                outline=c[p + "_outline"], ocolor=c[p + "_outline_color"], ow=c[p + "_outline_w"],
                glow=c[p + "_glow"], gcolor=c[p + "_glow_color"], gsize=c[p + "_glow_size"],
                shadow=c[p + "_shadow"], offy=c.get(p + "_offset_y", 0))

# ======================================================================================
#  Sprites (each returns (w, h, layers) in @2x design units)
# ======================================================================================
def shape_of(c, cx, cy, r):
    sh, rot = c["circle_shape"], c["circle_rotation"]
    if sh == "circle": return sd_circle(cx, cy, r)
    if sh == "square":
        s = r * 0.86
        sd = sd_box(cx - s, cy - s, cx + s, cy + s, s * c["circle_corner"] / 100.0)
    elif sh == "star":
        sd = sd_poly(star_pts(cx, cy, r, c["circle_star_points"], c["circle_star_inner"] / 100.0))
    else:
        sd = sd_poly(ngon(cx, cy, r, {"hexagon": 6, "octagon": 8, "pentagon": 5, "triangle": 3, "diamond": 4}[sh]))
    return sd_rot(sd, cx, cy, rot) if rot else sd

def pattern_fn(kind, period, ang):
    ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    tp = 2 * math.pi / period
    def m(x, y):
        u = ((x - 128) * ca + (y - 128) * sa) * tp
        v = (-(x - 128) * sa + (y - 128) * ca) * tp
        if kind == "stripes": return clamp(math.cos(u) * 2.5 + 0.5)
        if kind == "dots": return clamp(((math.cos(u) + math.cos(v)) / 2 - 0.35) * 5 + 0.5)
        if kind == "checker": return clamp(math.sin(u) * math.sin(v) * 3 + 0.5)
        return clamp(math.cos(math.hypot(x - 128, y - 128) * tp) * 2.5 + 0.5)
    return m

def sp_hitcircle(c):
    r = CR * c["circle_size"] / 100.0
    sd = shape_of(c, 128, 128, r)
    L = []
    if c["circle_shadow"]:
        L.append(L_fill(sd_shift(sd_grow(sd, 2), 0, c["circle_shadow_offset"]), (0, 0, 0, pct(c["circle_shadow_alpha"]))))
    a, f1, f2 = pct(c["circle_fill_alpha"]), hexrgb(c["circle_fill"]), hexrgb(c["circle_fill2"])
    mode, ang = c["circle_fill_mode"], math.radians(c["circle_grad_angle"])
    ca, sa = math.cos(ang), math.sin(ang)
    def col(x, y):
        if mode == "solid": t = 0.0
        elif mode == "radial": t = clamp(math.hypot(x - 128, y - 128) / r)
        else: t = clamp(((x - 128) * ca + (y - 128) * sa) / (2 * r) + 0.5)
        return mix(f1, f2, t) + (a,)
    L.append(L_fill(sd, col))
    if c["circle_pattern"] != "none" and c["circle_pattern_alpha"] > 0:
        L.append(masked(L_fill(sd, rgba(c["circle_pattern_color"], pct(c["circle_pattern_alpha"]))),
                        pattern_fn(c["circle_pattern"], c["circle_pattern_scale"], c["circle_pattern_angle"])))
    if c["circle_shine"]:
        def shine(x, y):
            u = ((x - 128) / (r * 0.75)) ** 2 + ((y - (128 - r * 0.5)) / (r * 0.38)) ** 2
            return max(0.0, 1 - u)
        L.append(masked(L_fill(sd, (255, 255, 255, pct(c["circle_shine_alpha"]))), shine))
    return 256, 256, L

def sp_overlay(c):
    r = CR * c["circle_size"] / 100.0
    sd = shape_of(c, 128, 128, r)
    L = []
    if c["circle_glow"]:
        L.append(L_glow(sd, c["circle_glow_size"], rgba(c["circle_glow_color"], pct(c["circle_glow_alpha"]))))
    w, st = c["circle_outline_w"], c["circle_outline_style"]
    col = rgba(c["circle_outline"], pct(c["circle_outline_alpha"]))
    if w:
        if st == "double":
            t = max(1.0, w * 0.36)
            L += [L_stroke(sd, t, col, t / 2), L_stroke(sd, t, col, w - t / 2)]
        else:
            ly = L_stroke(sd, w, col, w / 2)
            if st in ("dashed", "dotted"):
                ly = masked(ly, dash_mask(128, 128, c["circle_dash_count"] * (2 if st == "dotted" else 1), 0.55 if st == "dashed" else 0.3, r))
            L.append(ly)
    if c["circle_inner_on"]:
        iw = c["circle_inner_w"]
        L.append(L_stroke(sd_grow(sd, -(w + c["circle_inner_gap"])), iw, rgba(c["circle_inner_color"]), iw / 2))
    return 256, 256, L

def sp_approach(c):
    w = c["approach_w"]
    r = (124 - w / 2.0) * c["approach_radius"] / 100.0
    sd = shape_of(c, 128, 128, r) if c["approach_shape"] == "match" else sd_circle(128, 128, r)
    col = rgba(c["approach_color"], pct(c["approach_alpha"]))
    ring_sd, st, L = sd_stroke(sd, w), c["approach_style"], []
    if c["approach_fill"]: L.append(L_fill(sd, rgba(c["approach_color"], pct(c["approach_fill"]))))
    if st == "glow": L.append(L_glow(ring_sd, w * 2.5, col[:3] + (int(col[3] * 0.6),)))
    if st in ("dashed", "dotted"):
        n = c["approach_dash_count"] * (2 if st == "dotted" else 1)
        L.append(masked(L_fill(ring_sd, col), dash_mask(128, 128, n, 0.55 if st == "dashed" else 0.3, r)))
    else:
        L.append(L_fill(ring_sd, col))
    if st == "double":
        L.append(L_fill(sd_stroke(sd_grow(sd, -(w + c["approach_gap"])), w), col))
    return 256, 256, L

CUR = 192

def cursor_hot(c): return (14, 14) if c["cursor_shape"] == "arrow" else (CUR / 2, CUR / 2)

def cursor_geom(c):
    m, R, T, sh = CUR / 2, c["cursor_size"], c["cursor_weight"], c["cursor_shape"]
    fill = None
    if sh == "ring": body, fill = sd_stroke(sd_circle(m, m, R), T), sd_circle(m, m, R)
    elif sh == "dot": body = sd_circle(m, m, R * 0.5)
    elif sh == "cross": body = sd_union([sd_seg(m - R, m, m + R, m, T), sd_seg(m, m - R, m, m + R, T)])
    elif sh == "crosshair":
        rr, t = R * 0.62, T * 0.8
        body = sd_union([sd_stroke(sd_circle(m, m, rr), t), sd_seg(m - R, m, m - rr * 0.35, m, t), sd_seg(m + rr * 0.35, m, m + R, m, t),
                         sd_seg(m, m - R, m, m - rr * 0.35, t), sd_seg(m, m + rr * 0.35, m, m + R, t)])
        fill = sd_circle(m, m, rr)
    elif sh == "diamond": fill = sd_poly(ngon(m, m, R, 4)); body = sd_stroke(fill, T)
    elif sh == "square": fill = sd_box(m - R * 0.8, m - R * 0.8, m + R * 0.8, m + R * 0.8, T * 0.6); body = sd_stroke(fill, T)
    elif sh == "star": fill = sd_poly(star_pts(m, m, R, 5, 0.48)); body = sd_stroke(fill, T * 0.8)
    else:
        s = R / 52.0
        body = sd_poly([(14, 14), (14, 14 + 84 * s), (14 + 22 * s, 14 + 64 * s), (14 + 40 * s, 14 + 92 * s),
                        (14 + 54 * s, 14 + 84 * s), (14 + 36 * s, 14 + 58 * s), (14 + 62 * s, 14 + 58 * s)])
    ang = c["cursor_angle"]
    if ang and sh != "arrow":
        body = sd_rot(body, m, m, ang)
        if fill: fill = sd_rot(fill, m, m, ang)
    dot = sd_circle(m, m, c["cursor_dot"]) if sh not in ("dot", "arrow") and c["cursor_dot"] > 0 else None
    return body, fill, dot

def sp_cursor(c):
    body, fill, dot = cursor_geom(c)
    col, c2 = rgba(c["cursor_color"]), rgba(c["cursor_color2"])
    sep = c["cursor_middle"] and dot is not None
    allsd = sd_union([body] + ([dot] if dot and not sep else []))
    L = []
    if c["cursor_shadow"]: L.append(L_fill(sd_shift(allsd, 3, 5), (0, 0, 0, pct(c["cursor_shadow_alpha"]))))
    if c["cursor_glow"]: L.append(L_glow(allsd, c["cursor_glow_size"], rgba(c["cursor_glow_color"], 170)))
    if c["cursor_outline"]: L.append(L_fill(sd_grow(allsd, c["cursor_outline_w"]), rgba(c["cursor_outline_color"], pct(c["cursor_outline_alpha"]))))
    if fill and c["cursor_fill_alpha"]: L.append(L_fill(fill, c2[:3] + (pct(c["cursor_fill_alpha"]),)))
    L.append(L_fill(body, col))
    if dot and not sep: L.append(L_fill(dot, c2))
    return CUR, CUR, fade(L, c["cursor_alpha"] / 100.0)

def sp_cursormiddle(c):
    _, _, dot = cursor_geom(c)
    if dot is None: return TRANSPARENT
    return CUR, CUR, fade([L_fill(dot, rgba(c["cursor_color2"]))], c["cursor_alpha"] / 100.0)

def sp_trail(c):
    st, R = c["trail_style"], c["trail_size"]
    if st == "none": return TRANSPARENT
    col, col2 = hexrgb(c["trail_color"]), hexrgb(c["trail_color2"])
    if st == "dot": L = [L_fill(sd_circle(32, 32, R * 0.55), col + (210,))]
    elif st == "ring": L = [L_fill(sd_stroke(sd_circle(32, 32, R * 0.8), c["trail_weight"]), col + (220,))]
    elif st == "star": L = [L_fill(sd_poly(star_pts(32, 32, R * 0.9, 5, 0.45)), col + (220,))]
    else:
        L = [L_fill(sd_circle(32, 32, R), col2 + (40,)), L_fill(sd_circle(32, 32, R * 0.72), col + (90,)),
             L_fill(sd_circle(32, 32, R * c["trail_inner"] / 100.0), col + (170,))]
    return 64, 64, fade(L, c["trail_alpha"] / 100.0)

def sp_ball(c):
    st = c["ball_style"]
    if st == "none": return TRANSPARENT
    r, w = CR * c["ball_size"] / 100.0, c["ball_ring_w"]
    col, c2, fa = rgba(c["ball_color"]), hexrgb(c["ball_color2"]), pct(c["ball_fill_alpha"])
    L = []
    if st == "diamond":
        sd = sd_poly(ngon(128, 128, r, 4))
        outer = sd
        L += [L_fill(sd, c2 + (fa,))] + ([L_stroke(sd, w, col, w / 2)] if w else [])
    elif st == "disc":
        outer = sd_circle(128, 128, r); L.append(L_fill(outer, col))
    elif st == "glow":
        outer = sd_circle(128, 128, r * 0.8)
        L += [L_glow(outer, r * 0.4, col[:3] + (170,)), L_fill(outer, col)]
    else:
        outer = sd_circle(128, 128, r)
        L += [L_fill(sd_circle(128, 128, r - w * 0.5), c2 + (fa,))] + ([L_stroke(outer, w, col, w / 2)] if w else [])
    if c["ball_glow"]: L.insert(0, L_glow(outer, c["ball_glow_size"], col[:3] + (150,)))
    return 256, 256, fade(L, c["ball_alpha"] / 100.0)

def sp_follow(c):
    st = c["follow_style"]
    if st == "none": return TRANSPARENT
    r, w = 240 * c["follow_size"] / 100.0, c["follow_w"]
    col = rgba(c["follow_color"], pct(c["follow_alpha"]))
    ring_sd = sd_stroke(sd_circle(256, 256, r), w)
    L = []
    if st == "glow": L.append(L_glow(ring_sd, c["follow_glow_size"], col[:3] + (int(col[3] * 0.7),)))
    ly = L_fill(ring_sd, col)
    L.append(masked(ly, dash_mask(256, 256, c["follow_dash"], 0.55, r)) if st == "dashed" else ly)
    return 512, 512, L

def sp_reverse(c):
    s, T, fl = c["arrow_size"] / 100.0, c["arrow_weight"], -1 if c["arrow_flip"] else 1
    X = lambda dx: 64 + fl * dx * s
    Y = lambda dy: 64 + dy * s
    col = rgba(c["arrow_color"])
    st = c["arrow_style"]
    if st == "triangle": sd = sd_poly([(X(-24), Y(-32)), (X(30), Y(0)), (X(-24), Y(32))])
    elif st == "arrow":
        sd = sd_union([sd_seg(X(-34), Y(0), X(30), Y(0), T), sd_seg(X(4), Y(-26), X(34), Y(0), T), sd_seg(X(4), Y(26), X(34), Y(0), T)])
    else:
        sd = sd_union([sd_seg(X(-20), Y(-34), X(20), Y(0), T), sd_seg(X(-20), Y(34), X(20), Y(0), T)])
    return 128, 128, fade([L_fill(sd, col)], c["arrow_alpha"] / 100.0)

def sp_tick(c):
    r, st, col = c["tick_size"], c["tick_style"], rgba(c["tick_color"])
    if st == "ring": L = [L_fill(sd_stroke(sd_circle(24, 24, r), max(2.0, r * 0.35)), col)]
    elif st == "diamond": L = [L_fill(sd_poly(ngon(24, 24, r * 1.2, 4)), col)]
    else: L = [L_fill(sd_circle(24, 24, r), col)]
    return 48, 48, fade(L, c["tick_alpha"] / 100.0)

def sp_followpoint(c):
    R, st, col = c["fp_size"], c["fp_style"], rgba(c["fp_color"])
    if st == "line": sd = sd_seg(48 - R * 1.6, 32, 48 + R * 1.6, 32, R * 0.5)
    elif st == "arrow": sd = sd_union([sd_seg(48 - R * .6, 32 - R * .9, 48 + R * .6, 32, R * .45), sd_seg(48 - R * .6, 32 + R * .9, 48 + R * .6, 32, R * .45)])
    elif st == "chevron": sd = sd_poly([(48 - R * .7, 32 - R * .9), (48 + R * .8, 32), (48 - R * .7, 32 + R * .9)])
    else: sd = sd_circle(48, 32, R * 0.5)
    return 96, 64, fade([L_fill(sd, col)], c["fp_alpha"] / 100.0)

def sp_hit(c, key, text):
    j = key  # "hit300" etc
    o = dict(style=c["hit_style"], T=c["hit_weight"], slant=c["hit_slant"], color=c[j + "_color"], color2="#ffffff",
             gradient=False, size=c[j + "_scale"], alpha=c[j + "_alpha"], outline=c["hit_outline"], ocolor=c["hit_outline_color"],
             ow=c["hit_outline_w"], glow=c["hit_glow"], gcolor=c["hit_glow_color"], gsize=c["hit_glow_size"], shadow=c["hit_shadow"])
    return text_sprite(text, o)

def sp_hit0(c):
    k, sh = c["hit0_scale"] / 100.0, c["hit0_shape"]
    if sh == "plus": sd = sd_union([sd_seg(48, 16, 48, 80, 14), sd_seg(16, 48, 80, 48, 14)])
    elif sh == "dot": sd = sd_circle(48, 48, 30)
    elif sh == "ring": sd = sd_stroke(sd_circle(48, 48, 30), 12)
    elif sh == "bar": sd = sd_seg(16, 48, 80, 48, 16)
    else: sd = sd_union([sd_seg(18, 18, 78, 78, 14), sd_seg(78, 18, 18, 78, 14)])
    L = deco(sd, rgba(c["hit0_color"]), 150 if c["hit_shadow"] else 0,
             (c["hit_glow_size"], rgba(c["hit_glow_color"], 170)) if c["hit_glow"] else None,
             (c["hit_outline_w"], rgba(c["hit_outline_color"])) if c["hit_outline"] else None)
    return 96 * k + 40 * k, 96 * k + 40 * k, place(fade(L, c["hit0_alpha"] / 100.0), 20 * k, 20 * k, k)

def sp_spinner_circle(c):
    w, st = c["spinner_ring_w"], c["spinner_style"]
    r = 250 - w / 2.0
    col = rgba(c["spinner_color"], pct(c["spinner_alpha"] if False else 100))
    ring_sd = sd_stroke(sd_circle(256, 256, r), w)
    L = []
    if c["spinner_fill_alpha"]: L.append(L_fill(sd_circle(256, 256, r), rgba(c["spinner_color"], pct(c["spinner_fill_alpha"]))))
    ly = L_fill(ring_sd, col)
    L.append(masked(ly, dash_mask(256, 256, 36, 0.6, r)) if st == "dashed" else ly)
    if st == "double": L.append(L_fill(sd_stroke(sd_circle(256, 256, r - w - 14), max(2.0, w * 0.5)), col))
    n = c["spinner_ticks"]
    if n:
        segs = []
        for i in range(n):
            a = 2 * math.pi * i / n
            r1, r0 = r - w / 2 - 6, r - w / 2 - 6 - c["spinner_tick_len"]
            segs.append(sd_seg(256 + r0 * math.cos(a), 256 + r0 * math.sin(a), 256 + r1 * math.cos(a), 256 + r1 * math.sin(a), 6))
        L.append(L_fill(sd_union(segs), col))
    return 512, 512, fade(L, c["spinner_alpha"] / 100.0)

def sp_spinner_approach(c):
    w = c["spinner_approach_w"]
    return 512, 512, [L_fill(sd_stroke(sd_circle(256, 256, 250 - w / 2.0), w), rgba(c["spinner_approach_color"], pct(c["spinner_approach_alpha"])))]

SCORE_CH = {"comma": ",", "dot": ".", "percent": "%", "x": "x"}

class Sprites:
    """Lazily builds sprites; used by both the skin exporter and the preview."""
    def __init__(self, c): self.c, self.cache = c, {}
    def __getitem__(self, n):
        if n not in self.cache: self.cache[n] = self._build(n)
        return self.cache[n]
    def _build(self, n):
        c = self.c
        if n.startswith("default-"):
            d = n[8:]
            o = num_opts(c, "number")
            return text_sprite(d, o, c["number_d" + d] if c["number_per_digit"] else None)
        if n.startswith("score-"):
            k = n[6:]
            ch = SCORE_CH.get(k, k)
            return text_sprite(ch, num_opts(c, "score"), c["score_d" + ch] if c["score_per_digit"] and ch.isdigit() else None)
        if n.startswith("hit") and n[3:].isdigit() and n != "hit0":
            return sp_hit(c, n, n[3:])
        return {"hitcircle": sp_hitcircle, "hitcircleoverlay": sp_overlay, "approachcircle": sp_approach, "cursor": sp_cursor,
                "cursormiddle": sp_cursormiddle, "cursortrail": sp_trail, "sliderb0": sp_ball, "sliderfollowcircle": sp_follow,
                "reversearrow": sp_reverse, "sliderscorepoint": sp_tick, "followpoint": sp_followpoint, "hit0": sp_hit0,
                "spinner-circle": sp_spinner_circle, "spinner-approachcircle": sp_spinner_approach}[n](c)

def sprite_names(c):
    names = ["hitcircle", "hitcircleoverlay", "approachcircle", "cursor", "cursortrail", "sliderb0", "sliderfollowcircle",
             "reversearrow", "sliderscorepoint", "followpoint", "hit0", "hit50", "hit100", "hit300",
             "spinner-circle", "spinner-approachcircle"]
    names += [f"default-{d}" for d in "0123456789"] + [f"score-{d}" for d in "0123456789"]
    names += ["score-comma", "score-dot", "score-percent", "score-x"]
    if c["cursor_middle"] and cursor_geom(c)[2] is not None: names.append("cursormiddle")
    return names

# ======================================================================================
#  Sound synthesis (hit sounds as .wav)
# ======================================================================================
def synth(c, name, pitch=1.0, vol=1.0):
    g = lambda k: c[f"sn_{name}_{k}"]
    sr, loop = 44100, name in LOOPS
    attack, decay = g("attack") / 1000.0, g("decay") / 1000.0
    dur = max(0.03, min(2.5, decay if loop else attack + decay * 1.6))
    n = int(sr * dur)
    f0, f1 = g("freq") * pitch, g("sweep") * pitch
    rnd = random.Random(1234 + len(name))
    nm, harm = g("noise") / 100.0, g("harm") / 100.0
    drive = 1 + g("drive") * 0.08
    lp = 1 - math.exp(-2 * math.pi * min(g("lowpass") * pitch ** 0.5, sr / 2.2) / sr)
    levels, trem, vib, wave_t = 2 ** (g("crush") - 1), g("tremolo"), g("vibrato"), g("wave")
    tau = max(decay / 3.0, 0.001)
    out, ph, lpv = [], 0.0, 0.0
    for i in range(n):
        t = i / sr
        if loop: env = min(1.0, t / 0.004, (dur - t) / 0.004)
        else: env = (t / attack if (attack > 0 and t < attack) else math.exp(-(t - attack) / tau))
        fr = f0 if loop else f1 + (f0 - f1) * math.exp(-t * 7 / dur)
        if vib: fr *= 1 + 0.03 * math.sin(2 * math.pi * vib * t)
        ph += 2 * math.pi * fr / sr
        if wave_t == "noise":
            s = rnd.uniform(-1, 1)
        else:
            fp = (ph / (2 * math.pi)) % 1.0
            s = (math.sin(ph) if wave_t == "sine" else (1.0 if fp < 0.5 else -1.0) if wave_t == "square"
                 else 2 * fp - 1 if wave_t == "saw" else 2 * abs(2 * fp - 1) - 1)
            if harm: s = s * (1 - harm * 0.4) + harm * 0.4 * math.sin(2 * ph)
            if nm: s = s * (1 - nm) + rnd.uniform(-1, 1) * nm
        s = math.tanh(s * drive)
        lpv += lp * (s - lpv); s = lpv
        if trem: s *= 0.55 + 0.45 * math.cos(2 * math.pi * trem * t)
        if levels < 32768: s = round(s * levels) / levels
        out.append(s * env)
    ed, ea = int(sr * g("echo_ms") / 1000.0), g("echo") / 100.0
    if ea > 0:
        out += [0.0] * (ed * 3)
        for i in range(ed, len(out)): out[i] += out[i - ed] * ea
    peak = max(1e-9, max(abs(v) for v in out))
    k = g("volume") / 100.0 * vol * 0.95 / peak
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, v * k)) * 32767)) for v in out))
    return buf.getvalue()

def sound_files(c):
    f = {}
    if not c["sound_enabled"]: return f
    master = c["sound_master"] / 100.0
    for setname, on, pitch, vol in (("normal", c["sound_normal"], 1.0, 1.0),
                                    ("soft", c["sound_soft"], c["soft_pitch"] / 100.0, c["soft_volume"] / 100.0),
                                    ("drum", c["sound_drum"], c["drum_pitch"] / 100.0, c["drum_volume"] / 100.0)):
        if on:
            for name, _, _ in SAMPLES: f[f"{setname}-{name}.wav"] = synth(c, name, pitch, master * vol)
    return f

# ======================================================================================
#  Skin export
# ======================================================================================
def skin_ini(c):
    b = lambda v: int(bool(v))
    centre = {"auto": 0 if c["cursor_shape"] == "arrow" else 1, "centre": 1, "top-left": 0}[c["cursor_centre"]]
    rgbs = lambda h: "%d,%d,%d" % hexrgb(h)
    ini = ["[General]", f"Name: {c['name']}", f"Author: {c['author'] or 'Unknown'}", f"Version: {c['ini_version']}",
           f"CursorCentre: {centre}", f"CursorRotate: {b(c['cursor_rotate'])}", f"CursorExpand: {b(c['cursor_expand'])}",
           f"SliderBallFlip: {b(c['slider_ball_flip'])}", f"AllowSliderBallTint: {b(c['allow_slider_ball_tint'])}",
           f"HitCircleOverlayAboveNumber: {b(c['overlay_above_number'])}", f"SpinnerNoBlink: {b(c['spinner_no_blink'])}",
           f"SpinnerFadePlayfield: {b(c['spinner_fade_playfield'])}", f"SpinnerFrequencyModulate: {b(c['spinner_freq_mod'])}",
           f"LayeredHitSounds: {b(c['layered_hitsounds'])}", f"ComboBurstRandom: {b(c['combo_burst_random'])}",
           f"SamplesMatchPlaybackRate: {b(c['samples_match_rate'])}"]
    if c["animation_fps"]: ini.append(f"AnimationFramerate: {c['animation_fps']}")
    ini += ["", "[Colours]"]
    ini += [f"Combo{i}: {rgbs(h)}" for i, h in enumerate(c["combos"], 1)]
    ini.append(f"SliderBorder: {rgbs(c['slider_border'])}")
    if c["slider_track_on"]: ini.append(f"SliderTrackOverride: {rgbs(c['slider_track'])}")
    ini += [f"SpinnerBackground: {rgbs(c['ini_spinner_bg'])}", f"InputOverlayText: {rgbs(c['ini_input_text'])}",
            f"MenuGlow: {rgbs(c['ini_menu_glow'])}", f"SongSelectActiveText: {rgbs(c['ini_select_active'])}",
            f"SongSelectInactiveText: {rgbs(c['ini_select_inactive'])}", f"StarBreakAdditive: {rgbs(c['ini_star_break'])}",
            "", "[Fonts]", "HitCirclePrefix: default", f"HitCircleOverlap: {c['number_overlap']}",
            "ScorePrefix: score", f"ScoreOverlap: {c['score_overlap']}", "ComboPrefix: score", f"ComboOverlap: {c['combo_overlap']}", ""]
    return "\r\n".join(ini).encode()

def build_files(cfg):
    c = effective(norm(cfg))
    sp, f = Sprites(c), {}
    for n in sprite_names(c):
        w, h, lay = sp[n]
        f[n + "@2x.png"] = render(math.ceil(w), math.ceil(h), lay, 1.0)
        if c["export_1x"]: f[n + ".png"] = render(math.ceil(w / 2), math.ceil(h / 2), lay, 0.5)
    f.update(sound_files(c))
    f["skin.ini"] = skin_ini(c)
    return f

def make_osk(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in files.items(): z.writestr(n, d)
    return buf.getvalue()

def safe_name(n): return re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "", n).strip() or "skin"

# ======================================================================================
#  Preview scenes (built from the very same sprites that get exported)
# ======================================================================================
BGS = {"dark": (22, 22, 29), "light": (233, 233, 239), "mid": (96, 96, 110)}
SCORE_NAMES = {".": "dot", ",": "comma", "%": "percent", "x": "x"}

def make_scene_tools(c):
    sp = Sprites(c)
    def spr(name, cx, cy, k=1.0, tc=None, a=1.0, rot=0.0):
        w, h, lay = sp[name]
        if tc: lay = tint(lay, tc)
        return put(fade(lay, a), cx, cy, w, h, k, rot)
    def run(s, prefix, x, y, k, overlap, align="left"):
        names = [prefix + SCORE_NAMES.get(ch, ch) for ch in s]
        ws = [sp[n][0] * k for n in names]
        ov = overlap * 2 * k
        total = sum(ws) - ov * (len(ws) - 1)
        cur = x if align == "left" else x - total if align == "right" else x - total / 2
        out = []
        for n, wd in zip(names, ws):
            out += spr(n, cur + wd / 2, y, k); cur += wd - ov
        return out
    return sp, spr, run

def scene_layers(c):
    sp, spr, run = make_scene_tools(c)
    cb = [hexrgb(h) for h in c["combos"]]
    co = lambda i: cb[i % len(cb)]
    border = hexrgb(c["slider_border"])
    track = hexrgb(c["slider_track"]) if c["slider_track_on"] else tuple(int(v * 0.3) for v in co(2))
    def circle(cx, cy, label, combo, appk=None):
        out = spr("hitcircle", cx, cy, tc=combo)
        above = c["overlay_above_number"]
        if not above: out += spr("hitcircleoverlay", cx, cy)
        out += run(label, "default-", cx, cy, 1.0, c["number_overlap"], "center")
        if above: out += spr("hitcircleoverlay", cx, cy)
        if appk: out += spr("approachcircle", cx, cy, k=appk, tc=combo)
        return out
    L = []
    # follow points between the first two circles, and from the second to the slider
    for (ax, ay), (bx, by) in (((230, 210), (470, 360)), ((470, 360), (780, 250))):
        dx, dy = bx - ax, by - ay; dist = math.hypot(dx, dy); ang = math.degrees(math.atan2(dy, dx))
        d = 150
        while d < dist - 130:
            L += spr("followpoint", ax + dx * d / dist, ay + dy * d / dist, rot=ang); d += 56
    # slider
    y = 250
    L += [L_fill(sd_seg(780, y, 1080, y, 236), border + (255,)), L_fill(sd_seg(780, y, 1080, y, 212), track + (255,))]
    L += spr("hitcircle", 1080, y, tc=co(2)) + spr("hitcircleoverlay", 1080, y) + spr("reversearrow", 1080, y)
    L += circle(780, y, "11", co(2))
    for tx in (870, 915, 1020): L += spr("sliderscorepoint", tx, y)
    L += spr("sliderfollowcircle", 960, y, k=0.62) + spr("sliderb0", 960, y)
    # circles
    L += circle(470, 360, "10", co(1), 1.7)
    L += circle(230, 210, "9", co(0), 1.35)
    # spinner
    L += spr("spinner-circle", 1010, 500, k=0.4) + spr("spinner-approachcircle", 1010, 500, k=0.5)
    # hit results
    for name, x in (("hit300", 330), ("hit100", 520), ("hit50", 668), ("hit0", 775)):
        L += spr(name, x, 650, 0.75)
    # score, accuracy, combo
    L += run("1,234,567", "score-", 1255, 36, 0.46, c["score_overlap"], "right")
    L += run("98.50%", "score-", 1255, 84, 0.36, c["score_overlap"], "right")
    L += run("142x", "score-", 24, 676, 0.6, c["combo_overlap"], "left")
    # trail + cursor
    tx, ty = 1150, 600
    for i in range(8):
        t = i / 7
        L += spr("cursortrail", 980 + (tx - 980) * t, 690 + (ty - 690) * t, a=0.15 + 0.85 * t)
    hx, hy = cursor_hot(c)
    w, h, lay = sp["cursor"]
    L += place(lay, tx - hx, ty - hy)
    if "cursormiddle" in sprite_names(c): L += place(sp["cursormiddle"][2], tx - hx, ty - hy)
    return L

def cursor_layers(c):
    sp, spr, run = make_scene_tools(c)
    px, py, k = 250, 150, 1.8
    hx, hy = cursor_hot(c)
    L = []
    for i in range(6):
        t = i / 5
        L += spr("cursortrail", 70 + (px - 70) * t, 230 + (py - 230) * t, k=k, a=0.15 + 0.85 * t)
    L += place(sp["cursor"][2], px - hx * k, py - hy * k, k)
    if "cursormiddle" in sprite_names(c): L += place(sp["cursormiddle"][2], px - hx * k, py - hy * k, k)
    return L

def font_layers(c):
    sp, spr, run = make_scene_tools(c)
    L = run("0123456789", "default-", 20, 52, 0.8, c["number_overlap"])
    L += run("0123456789,.%x", "score-", 20, 140, 0.8, c["score_overlap"])
    for name, x in (("hit300", 80), ("hit100", 250), ("hit50", 400), ("hit0", 510)):
        L += spr(name, x, 228, 0.8)
    return L

def preview_png(cfg, view="scene", scale=0.5, bg="dark"):
    c = effective(norm(cfg))
    back = BGS.get(bg, BGS["dark"])
    if view == "cursor": return render(400, 300, cursor_layers(c), 1.0, back)
    if view == "font": return render(720, 270, font_layers(c), 1.0, back)
    s = 0.15 if view == "thumb" else max(0.2, min(2.0, float(scale)))
    return render(int(1280 * s), int(720 * s), scene_layers(c), s, back)

def icon_png(size=256):
    g = lambda x, y: (int(255 + (122 - 255) * y / 256), int(79 + (77 - 79) * y / 256), int(154 + (255 - 154) * y / 256), 255)
    L = [L_fill(sd_box(8, 8, 248, 248, 56), g), L_fill(sd_stroke(sd_circle(124, 120, 70), 16), (255, 255, 255, 255))]
    sd, wid = text_sd("1", "rounded", 14, 0)
    L += place([L_fill(sd, (255, 255, 255, 255))], 124 - DW * 0.85 / 2, 120 - DH * 0.85 / 2, 0.85)
    pts = [(150, 150), (150, 216), (167, 200), (181, 222), (192, 216), (178, 196), (198, 196)]
    arrow = sd_poly(pts)
    L += [L_fill(sd_grow(arrow, 2.5), (40, 20, 80, 220)), L_fill(arrow, (255, 255, 255, 255))]
    return render(size, size, L, size / 256.0)

# ======================================================================================
#  The app: local web server + window
# ======================================================================================
PAGE = r"""<!doctype html><html><head><meta charset=utf-8><title>osu! Skin Maker</title>
<link rel=icon href=/icon.png><meta name=viewport content="width=device-width,initial-scale=1">
<style>
:root{color-scheme:light dark;--bg:#f4f4f8;--pn:#fff;--tx:#1d1d26;--mu:#76768a;--bd:#dcdce6;--ac:#e8387f;--ac2:#fff}
@media(prefers-color-scheme:dark){:root{--bg:#14141b;--pn:#1d1d27;--tx:#ececf4;--mu:#8d8da2;--bd:#2e2e3d;--ac:#ff4f9a}}
*{box-sizing:border-box}html,body{height:100%;margin:0}
body{font:13.5px system-ui,sans-serif;background:var(--bg);color:var(--tx);display:flex;flex-direction:column}
header{display:flex;gap:8px;align-items:center;padding:8px 12px;background:var(--pn);border-bottom:1px solid var(--bd);flex-wrap:wrap}
header img{width:28px;height:28px;border-radius:7px}header b{font-size:15px}
input[type=text],input[type=search],select{padding:6px 8px;border:1px solid var(--bd);border-radius:8px;background:var(--bg);color:var(--tx);font:inherit}
button{padding:6px 10px;border:1px solid var(--bd);border-radius:8px;background:var(--pn);color:var(--tx);font:inherit;cursor:pointer}
button:hover{border-color:var(--ac)}button:disabled{opacity:.4;cursor:default}
button.p{background:var(--ac);border-color:var(--ac);color:var(--ac2);font-weight:600}
main{flex:1;display:grid;grid-template-columns:190px 1fr 410px;min-height:0}
aside,section{overflow:auto;padding:12px}aside{background:var(--pn);border-right:1px solid var(--bd)}
#side2{background:var(--pn);border-left:1px solid var(--bd);border-right:0;padding:0}
#tools{position:sticky;top:0;z-index:2;background:var(--pn);padding:10px 12px;border-bottom:1px solid var(--bd);display:flex;flex-direction:column;gap:8px}
#tools .r{display:flex;gap:6px;flex-wrap:wrap}#tools input[type=search]{width:100%}
#panel{padding:10px 12px}
h3{margin:2px 0 10px;font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--mu)}
.card{display:flex;flex-direction:column;gap:4px;position:relative;margin-bottom:10px;padding:6px;border:1px solid var(--bd);border-radius:10px;cursor:pointer}
.card:hover{border-color:var(--ac)}.card img{width:100%;border-radius:6px;background:#222;min-height:40px}
.card button{position:absolute;top:8px;right:8px;padding:0 7px;line-height:20px}
.muted{color:var(--mu)}
.view{display:flex;flex-direction:column;gap:12px;align-items:center}
.view img{max-width:100%;border-radius:12px;border:1px solid var(--bd);background:#222}
.cap{align-self:flex-start;color:var(--mu);font-size:12px}
details{border:1px solid var(--bd);border-radius:10px;margin-bottom:8px;padding:0 10px}
summary{cursor:pointer;font-weight:600;padding:8px 0;display:flex;gap:8px;align-items:center}
summary span:first-child{flex:1}
.badge{font-size:11px;background:var(--ac);color:var(--ac2);border-radius:9px;padding:0 7px;display:none}
details.has .badge{display:inline}
.grst{font-size:11px;padding:1px 6px;display:none}details.has .grst{display:inline}
.row{display:grid;grid-template-columns:1fr 118px 40px 18px;gap:6px;align-items:center;padding:4px 0}
.row label{color:var(--mu)}.row.chg label{color:var(--tx);font-weight:600}
.row .val{font-weight:500;text-align:right;font-size:12px}
.row input[type=color]{width:118px;height:26px;padding:0;border:1px solid var(--bd);border-radius:6px;background:none}
.row input[type=range]{width:118px}.row select{width:118px;padding:4px}.row input[type=checkbox]{justify-self:start}
.rst{padding:0;border:0;background:none;color:var(--mu);visibility:hidden}.row.chg .rst{visibility:visible}
.row.play{grid-template-columns:1fr auto}
#combos{display:flex;gap:8px;flex-wrap:wrap;padding:4px 0 10px}
.sw{position:relative}.sw input{width:42px;height:42px;border:1px solid var(--bd);border-radius:10px;padding:0;background:none}
.sw button{position:absolute;top:-6px;right:-6px;padding:0 5px;line-height:16px;border-radius:9px;font-size:12px}
.add{width:42px;height:42px;font-size:20px}
#toast{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);background:var(--tx);color:var(--bg);padding:9px 16px;border-radius:20px;opacity:0;transition:.2s;pointer-events:none}
#toast.on{opacity:1}#busy{color:var(--mu);font-size:12px}
@media(max-width:1000px){main{grid-template-columns:1fr 380px}aside:first-child{display:none}}
</style></head><body>
<header><img src=/icon.png><b>osu! Skin Maker</b><span class=muted id=nopt></span>
<input type=text id=name placeholder="Skin name" style="width:140px"><input type=text id=author placeholder="Author" style="width:110px">
<select id=preset><option value="">Preset…</option></select>
<select id=bg title="Preview background"><option value=dark>Dark bg</option><option value=mid>Mid bg</option><option value=light>Light bg</option></select>
<span id=busy hidden>rendering…</span><span style="flex:1"></span>
<button id=save>Save to library</button><button id=png>Save preview</button><button id=dl class=p>Download .osk</button></header>
<main>
<aside><h3>My skins</h3><div id=lib></div></aside>
<section><div class=view>
<div class=cap>Live preview. It is drawn by the same code that writes your skin files.</div>
<img id=scene alt=preview width=640 height=360>
<div class=cap>Cursor close-up with trail</div><img id=cursor alt=cursor width=400 height=300>
<div class=cap>Numbers, score font and hit results</div><img id=font alt=fonts width=720 height=270></div></section>
<aside id=side2><div id=tools>
<input type=search id=q placeholder="Search all options (e.g. glow, cursor, pitch)…">
<div class=r><button id=undo disabled>↶ Undo</button><button id=redo disabled>↷ Redo</button>
<button id=rc title="Random color scheme">🎲 Colors</button><button id=rs title="Random shapes and styles">🎲 Styles</button>
<button id=exp>Export</button><button id=imp>Import</button><button id=rall>Reset all</button><input type=file id=file accept=.json hidden></div>
<div class=muted id=chg></div></div>
<div id=panel><details open><summary><span>Combo colors</span></summary><div id=combos></div></details><div id=controls></div></div></aside>
</main><div id=toast></div>
<script>
const $=s=>document.querySelector(s);
let S,cfg,seq=0,timer,ctimer,hist=[],hi=-1,restoring=false,audio;const inputs={},rows={},groups=[];
const post=(u,b)=>fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});
const clone=o=>JSON.parse(JSON.stringify(o)),same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
function toast(m){const t=$('#toast');t.textContent=m;t.classList.add('on');clearTimeout(toast.t);toast.t=setTimeout(()=>t.classList.remove('on'),2600)}
async function show(sel,res){const u=URL.createObjectURL(await res.blob()),im=$(sel);if(im.dataset.u)URL.revokeObjectURL(im.dataset.u);im.dataset.u=u;im.src=u}
function schedule(){clearTimeout(timer);timer=setTimeout(refresh,150);clearTimeout(ctimer);ctimer=setTimeout(commit,600)}
async function refresh(){const n=++seq,bg=$('#bg').value;$('#busy').hidden=false;
  const q=(view,scale)=>post('/api/preview',{cfg,view,scale,bg,seq:n}).then(r=>r.status===200?r:null).catch(()=>null);
  try{const f=await q('scene',.3);if(n!==seq)return;if(f)await show('#scene',f);
    const [full,cur,fnt]=await Promise.all([q('scene',.5),q('cursor'),q('font')]);if(n!==seq)return;
    if(full)await show('#scene',full);if(cur)await show('#cursor',cur);if(fnt)await show('#font',fnt)}catch(e){}
  if(n===seq)$('#busy').hidden=true}
function commit(){if(restoring)return;const s=JSON.stringify(cfg);if(hist[hi]===s)return;hist=hist.slice(0,hi+1);hist.push(s);if(hist.length>100)hist.shift();hi=hist.length-1;hbtn()}
function hbtn(){$('#undo').disabled=hi<=0;$('#redo').disabled=hi>=hist.length-1}
function jump(d){clearTimeout(ctimer);commit();const n=hi+d;if(n<0||n>=hist.length)return;hi=n;cfg=JSON.parse(hist[hi]);restoring=true;sync();restoring=false;hbtn()}
function mark(k){const f=S.byKey[k],ch=!same(cfg[k],S.defaults[k]);rows[k].classList.toggle('chg',ch);const g=groups[f.gi];g.n=g.keys.filter(x=>!same(cfg[x],S.defaults[x])).length;g.el.classList.toggle('has',g.n>0);g.badge.textContent=g.n}
function counter(){let n=S.allKeys.filter(k=>!same(cfg[k],S.defaults[k])).length;if(!same(cfg.combos,S.defaults.combos))n++;$('#chg').textContent=n?n+' options changed':'All options at default'}
function set(k,v){cfg[k]=v;mark(k);counter();schedule()}
function row(f){const w=document.createElement('div');w.className='row'+(f.t==='play'?' play':'');const l=document.createElement('label');l.textContent=f.l;w.append(l);
  if(f.t==='play'){const b=document.createElement('button');b.textContent='▶ Play';b.onclick=()=>play(f.k.slice(5));w.append(b);return w}
  let i;const v=document.createElement('b');v.className='val';
  if(f.t==='select'){i=document.createElement('select');f.o.forEach(o=>i.add(new Option(o,o)));i.onchange=()=>set(f.k,i.value)}
  else if(f.t==='range'){i=document.createElement('input');i.type='range';i.min=f.min;i.max=f.max;i.oninput=()=>{v.textContent=i.value+(f.u||'');set(f.k,+i.value)}}
  else if(f.t==='bool'){i=document.createElement('input');i.type='checkbox';i.onchange=()=>set(f.k,i.checked)}
  else{i=document.createElement('input');i.type='color';i.oninput=()=>set(f.k,i.value)}
  i._v=v;i._u=f.u||'';const r=document.createElement('button');r.className='rst';r.textContent='↺';r.title='Reset to default';r.onclick=()=>{cfg[f.k]=clone(S.defaults[f.k]);paint(f.k);mark(f.k);counter();schedule()};
  w.append(i,v,r);inputs[f.k]=i;rows[f.k]=w;return w}
function paint(k){const i=inputs[k];if(i.type==='checkbox')i.checked=!!cfg[k];else{i.value=cfg[k];if(i._v)i._v.textContent=i.type==='range'?cfg[k]+i._u:''}}
function combos(){const box=$('#combos');box.innerHTML='';
  cfg.combos.forEach((c,i)=>{const d=document.createElement('div');d.className='sw';const p=document.createElement('input');p.type='color';p.value=c;p.oninput=()=>{cfg.combos[i]=p.value;counter();schedule()};d.append(p);
    if(cfg.combos.length>1){const x=document.createElement('button');x.textContent='×';x.title='Remove';x.onclick=()=>{cfg.combos.splice(i,1);combos();counter();schedule()};d.append(x)}box.append(d)});
  if(cfg.combos.length<8){const a=document.createElement('button');a.textContent='+';a.className='add';a.title='Add combo color';a.onclick=()=>{cfg.combos.push('#ffffff');combos();counter();schedule()};box.append(a)}}
function sync(){for(const k in inputs){paint(k);mark(k)}$('#name').value=cfg.name;$('#author').value=cfg.author;combos();counter();schedule()}
function load(c,keepId){const keep={name:cfg.name,author:cfg.author};cfg=Object.assign(clone(S.defaults),clone(c));if(keepId){cfg.name=keep.name;cfg.author=keep.author}sync()}
function filter(){const t=$('#q').value.trim().toLowerCase();
  groups.forEach(g=>{let any=false;g.fields.forEach(f=>{const m=!t||(f.l+' '+f.k+' '+g.name).toLowerCase().includes(t);rows[f.k]&&(rows[f.k].hidden=!m);any=any||m});
    g.el.hidden=!any;if(t&&any)g.el.open=true;if(!t)g.el.open=g.def})}
function hsl(h,s,l){h/=360;const f=n=>{const k=(n+h*12)%12,a=s*Math.min(l,1-l);return Math.round(255*(l-a*Math.max(-1,Math.min(k-3,9-k,1)))).toString(16).padStart(2,'0')};return '#'+f(0)+f(8)+f(4)}
const skipG=/^(Global|skin\.ini|Sound|Export)/;
function randColors(){const base=Math.random()*360,n=3+Math.floor(Math.random()*4);cfg.combos=Array.from({length:n},(_,i)=>hsl((base+i*360/n)%360,.85,.6));
  const a=hsl((base+180)%360,.9,.62),b=hsl((base+35)%360,.8,.72);
  S.schema.forEach(g=>{if(skipG.test(g.g))return;g.f.forEach(f=>{if(f.t!=='color'||/outline_color|slider_track|_d\d$/.test(f.k))return;const p=Math.random();cfg[f.k]=p<.4?'#ffffff':p<.75?a:b})});sync()}
function randStyles(){S.schema.forEach(g=>{if(skipG.test(g.g))return;g.f.forEach(f=>{if(f.t==='select'&&Math.random()<.8){let o=f.o.filter(x=>x!=='none');cfg[f.k]=o[Math.floor(Math.random()*o.length)]}
  else if(f.t==='bool'&&/glow|shine|outline|shadow/.test(f.k)&&Math.random()<.3)cfg[f.k]=!cfg[f.k]})});sync()}
async function play(name){const r=await post('/api/sound',{cfg,name});if(!r.ok){toast('Could not render that sound');return}
  const u=URL.createObjectURL(await r.blob());if(audio)audio.pause();audio=new Audio(u);audio.play()}
async function skins(){const r=await (await fetch('/api/skins')).json(),box=$('#lib');
  box.innerHTML=r.length?'':'<p class=muted>Nothing saved yet. Use "Save to library".</p>';
  for(const s of r){const d=document.createElement('div');d.className='card';const im=document.createElement('img'),t=document.createElement('span'),x=document.createElement('button');
    t.textContent=s.name;x.textContent='×';x.title='Delete';d.onclick=()=>load(s.cfg);
    x.onclick=async e=>{e.stopPropagation();await fetch('/api/skins/'+encodeURIComponent(s.name),{method:'DELETE'});skins()};
    d.append(im,t,x);box.append(d);post('/api/preview',{cfg:s.cfg,view:'thumb',bg:$('#bg').value}).then(r=>r.blob()).then(b=>im.src=URL.createObjectURL(b))}}
async function download(path,body,fname){const r=await post(path,body);if(!r.ok){toast('Something went wrong');return false}
  const a=document.createElement('a');a.href=URL.createObjectURL(await r.blob());a.download=fname;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),5000);return true}
$('#dl').onclick=async()=>{toast('Building skin and sounds, this takes several seconds…');if(await download('/api/build',{cfg},(cfg.name||'skin')+'.osk'))toast('Done! Open the .osk with osu!')};
$('#png').onclick=async()=>{toast('Rendering…');await download('/api/preview',{cfg,view:'scene',scale:1,bg:$('#bg').value},(cfg.name||'skin')+'-preview.png')};
$('#save').onclick=async()=>{const r=await post('/api/skins',{cfg});toast(r.ok?'Saved to library':'Could not save');skins()};
$('#exp').onclick=()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(cfg,null,1)],{type:'application/json'}));a.download=(cfg.name||'skin')+'.json';a.click()};
$('#imp').onclick=()=>$('#file').click();
$('#file').onchange=async e=>{const f=e.target.files[0];if(!f)return;try{const j=JSON.parse(await f.text());const r=await post('/api/norm',{cfg:j});load(await r.json());toast('Imported')}catch(x){toast('Not a valid settings file')}e.target.value=''};
$('#rall').onclick=()=>{if(confirm('Reset every option to its default?'))load(S.defaults,true)};
$('#undo').onclick=()=>jump(-1);$('#redo').onclick=()=>jump(1);$('#rc').onclick=randColors;$('#rs').onclick=randStyles;
$('#name').oninput=e=>{cfg.name=e.target.value};$('#author').oninput=e=>{cfg.author=e.target.value};
$('#bg').onchange=()=>{schedule();skins()};$('#q').oninput=filter;
addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key==='z'&&!/INPUT|SELECT/.test(document.activeElement.tagName)){e.preventDefault();jump(e.shiftKey?1:-1)}});
(async()=>{S=await (await fetch('/api/schema')).json();cfg=clone(S.defaults);S.byKey={};S.allKeys=[];
  const host=$('#controls');S.schema.forEach((g,gi)=>{const d=document.createElement('details');const s=document.createElement('summary');const nm=document.createElement('span');nm.textContent=g.g;
    const bd=document.createElement('span');bd.className='badge';const rs=document.createElement('button');rs.className='grst';rs.textContent='reset';
    s.append(nm,bd,rs);d.append(s);const keys=[],fields=[];
    g.f.forEach(f=>{f.gi=gi;S.byKey[f.k]=f;d.append(row(f));if(f.t!=='play'){keys.push(f.k);S.allKeys.push(f.k)}fields.push(f)});
    const G={el:d,badge:bd,keys,fields,name:g.g,n:0,def:gi===2||gi===4};d.open=G.def;groups.push(G);
    rs.onclick=e=>{e.preventDefault();keys.forEach(k=>{cfg[k]=clone(S.defaults[k]);paint(k);mark(k)});counter();schedule()};host.append(d)});
  const ps=$('#preset');Object.keys(S.presets).forEach(p=>ps.add(new Option(p,p)));
  ps.onchange=()=>{if(ps.value){load(S.presets[ps.value],true);ps.value=''}};
  $('#nopt').textContent=S.nopt+' options';
  sync();commit();skins();setInterval(()=>fetch('/ping'),4000);addEventListener('pagehide',()=>navigator.sendBeacon('/api/bye'))})();
</script></body></html>"""

CHROMIUMS = ["google-chrome-stable", "google-chrome", "chromium", "chromium-browser", "brave-browser",
             "microsoft-edge", "microsoft-edge-stable", "vivaldi", "opera"]
FLATPAK_CHROMIUMS = ["com.google.Chrome", "org.chromium.Chromium", "com.brave.Browser", "com.microsoft.Edge",
                     "io.github.ungoogled_software.ungoogled_chromium"]

def launch_app_window(url):
    """Open the UI in a standalone app window (no tabs / address bar). Needs a Chromium based browser."""
    args = [f"--app={url}", "--window-size=1380,860"]
    for b in CHROMIUMS:
        p = shutil.which(b)
        if p:
            subprocess.Popen([p] + args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return True
    if shutil.which("flatpak"):
        try:
            have = subprocess.run(["flatpak", "list", "--app", "--columns=application"], capture_output=True, text=True, timeout=10).stdout.split()
        except Exception:
            have = []
        for b in FLATPAK_CHROMIUMS:
            if b in have:
                subprocess.Popen(["flatpak", "run", b] + args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                return True
    return False

def lib_path(name): return os.path.join(LIB, safe_name(name) + ".json")

def serve(want_app=True):
    state = {"ping": time.time(), "bye": 0.0, "seq": 0}
    cache, lock = {}, threading.Lock()

    def cached(key, make):
        with lock:
            hit = cache.get(key)
        if hit is None:
            hit = make()
            with lock:
                if len(cache) > 60: cache.clear()
                cache[key] = hit
        return hit

    class H(http.server.BaseHTTPRequestHandler):
        def _out(self, body, ctype, code=200, extra=()):
            self.send_response(code)
            self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in extra: self.send_header(k, v)
            self.end_headers(); self.wfile.write(body)

        def _json(self, obj, code=200): self._out(json.dumps(obj).encode(), "application/json", code)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            try: return json.loads(raw.decode() or "{}")
            except ValueError: return {}

        def do_GET(self):
            state["ping"] = time.time()
            path = urllib.parse.urlparse(self.path).path
            if path == "/": self._out(PAGE.encode(), "text/html; charset=utf-8")
            elif path == "/ping": self._out(b"ok", "text/plain")
            elif path == "/icon.png": self._out(cached("icon", lambda: icon_png(256)), "image/png")
            elif path == "/api/schema":
                self._json({"schema": SCHEMA, "presets": PRESETS, "defaults": DEFAULTS, "nopt": NOPT})
            elif path == "/api/skins":
                out = []
                if os.path.isdir(LIB):
                    for fn in sorted(os.listdir(LIB)):
                        if fn.endswith(".json"):
                            try: c = norm(json.load(open(os.path.join(LIB, fn))))
                            except Exception: continue
                            out.append({"name": c["name"], "cfg": c})
                self._json(out)
            else: self._out(b"not found", "text/plain", 404)

        def do_POST(self):
            state["ping"] = time.time()
            path = urllib.parse.urlparse(self.path).path
            if path == "/api/bye":
                state["bye"] = time.time(); self._out(b"", "text/plain"); return
            data = self._body()
            try:
                if path == "/api/preview":
                    s = data.get("seq")
                    if isinstance(s, int):
                        if s < state["seq"] - 0 and data.get("view") != "thumb" and s != 0 and state["seq"] - s > 1:
                            self._out(b"", "text/plain", 204); return   # a newer edit already arrived
                        state["seq"] = max(state["seq"], s)
                    view, scale, bg = data.get("view", "scene"), data.get("scale", .5), data.get("bg", "dark")
                    key = hashlib.sha1(json.dumps([norm(data.get("cfg")), view, scale, bg], sort_keys=True).encode()).hexdigest()
                    self._out(cached(key, lambda: preview_png(data.get("cfg"), view, scale, bg)), "image/png")
                elif path == "/api/sound":
                    c = effective(norm(data.get("cfg"))); name = str(data.get("name"))
                    if name not in [s[0] for s in SAMPLES]: self._out(b"unknown sample", "text/plain", 400); return
                    key = hashlib.sha1(json.dumps([c, name], sort_keys=True).encode()).hexdigest()
                    self._out(cached(key, lambda: synth(c, name, 1.0, c["sound_master"] / 100.0)), "audio/wav")
                elif path == "/api/norm": self._json(norm(data.get("cfg")))
                elif path == "/api/build":
                    c = norm(data.get("cfg"))
                    fn = urllib.parse.quote(safe_name(c["name"])) + ".osk"
                    self._out(make_osk(build_files(c)), "application/octet-stream",
                              extra=[("Content-Disposition", f"attachment; filename*=UTF-8''{fn}")])
                elif path == "/api/skins":
                    c = norm(data.get("cfg")); os.makedirs(LIB, exist_ok=True)
                    with open(lib_path(c["name"]), "w") as fh: json.dump(c, fh, indent=1)
                    self._json({"ok": True})
                else: self._out(b"not found", "text/plain", 404)
            except Exception as e:
                self._out(str(e).encode(), "text/plain", 500)

        def do_DELETE(self):
            path = urllib.parse.unquote(urllib.parse.urlparse(self.path).path)
            if path.startswith("/api/skins/"):
                try: os.remove(lib_path(path[len("/api/skins/"):]))
                except OSError: pass
                self._json({"ok": True})
            else: self._out(b"not found", "text/plain", 404)

        def log_message(self, *a): pass

    class Srv(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True

    srv = Srv(("127.0.0.1", 0), H)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    app_mode = want_app and launch_app_window(url)
    if not app_mode:
        webbrowser.open(url)
        print(f"{APP} running at {url}  (press Ctrl+C to quit)")
    else:  # the window is the app: quit when it closes
        def watch():
            while True:
                time.sleep(2); now = time.time()
                if state["bye"] and now - state["bye"] > 6 and state["ping"] < state["bye"]: break
                if now - state["ping"] > 180: break
            srv.shutdown()
        threading.Thread(target=watch, daemon=True).start()
    try: srv.serve_forever()
    except KeyboardInterrupt: pass

# ======================================================================================
#  CLI
# ======================================================================================
def main():
    p = argparse.ArgumentParser(description="osu! Skin Maker. Run with no arguments to open the app.")
    p.add_argument("name", nargs="?", help="skin name (skips the app and writes the skin directly)")
    p.add_argument("--browser", action="store_true", help="open in a normal browser tab instead of an app window")
    p.add_argument("--author", default="")
    p.add_argument("--preset", choices=PRESETS, help="start from a preset")
    p.add_argument("--config", metavar="FILE", help="load settings exported from the app (JSON)")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="set any option, e.g. cursor_shape=arrow")
    p.add_argument("--colors", help="combo colors, comma separated hex")
    p.add_argument("--ring", help="circle outline color (hex)")
    p.add_argument("--cursor", help="cursor color (hex)")
    p.add_argument("--folder", action="store_true", help="write an unzipped folder instead of an .osk")
    p.add_argument("--out", default=".", help="output directory")
    p.add_argument("--list-options", action="store_true", help="print all options and exit")
    p.add_argument("--dump-config", action="store_true", help="print the final settings as JSON and exit")
    p.add_argument("--make-icon", metavar="PATH", help="write the app icon PNG and exit")
    a = p.parse_args()

    if a.list_options:
        print(f"{NOPT} options in {len(SCHEMA)} groups (counting the 8 combo color slots)\n")
        for g in SCHEMA:
            print(f"[{g['g']}]")
            for f in g["f"]:
                if f["t"] == "play": continue
                extra = "/".join(f["o"]) if f["t"] == "select" else f"{f['min']}..{f['max']}{f['u']}" if f["t"] == "range" else f["t"]
                print(f"  {f['k']:<26} {extra:<46} default: {f['d']}")
        return
    if a.make_icon:
        os.makedirs(os.path.dirname(os.path.abspath(a.make_icon)), exist_ok=True)
        open(a.make_icon, "wb").write(icon_png(256)); print("Wrote", a.make_icon); return
    if not a.name and not a.dump_config:
        return serve(want_app=not a.browser)

    cfg = json.loads(json.dumps(DEFAULTS))
    if a.config: cfg.update(json.load(open(a.config)))
    if a.preset: cfg.update(PRESETS[a.preset])
    if a.name: cfg["name"] = a.name
    if a.author: cfg["author"] = a.author
    if a.colors: cfg["combos"] = [x.strip() for x in a.colors.split(",")]
    if a.ring: cfg["circle_outline"] = cfg["slider_border"] = a.ring
    if a.cursor: cfg["cursor_color"] = a.cursor
    for kv in a.set:
        if "=" not in kv: sys.exit(f"--set needs KEY=VALUE, got '{kv}'")
        k, v = kv.split("=", 1)
        if k not in DEFAULTS: sys.exit(f"Unknown option '{k}'. Try --list-options")
        cfg[k] = v
    if a.dump_config:
        print(json.dumps(norm(cfg), indent=1)); return
    print("Building skin (images + sounds), this takes several seconds...")
    files = build_files(cfg)
    os.makedirs(a.out, exist_ok=True)
    safe = safe_name(cfg["name"])
    if a.folder:
        d = os.path.join(a.out, safe); os.makedirs(d, exist_ok=True)
        for n, data in files.items(): open(os.path.join(d, n), "wb").write(data)
        print("Wrote folder", d)
    else:
        path = os.path.join(a.out, safe + ".osk")
        open(path, "wb").write(make_osk(files)); print("Wrote", path)

if __name__ == "__main__":
    main()
