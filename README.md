# osu! Skin Maker

A small desktop app for designing osu! skins with a live preview, then exporting an `.osk`.
357 options across hit circles, numbers, approach circles, cursor, trail, sliders, spinner,
score font, hit results, hit sounds and skin.ini. Pure Python, no root, no git, no pip.

Repo: https://github.com/brendenthebanana-hash/OsuSkinners

## Install (openSUSE or any Linux, no root)

    curl -fsSL https://raw.githubusercontent.com/brendenthebanana-hash/OsuSkinners/main/install.sh | sh

If your default branch is `master`:

    curl -fsSL https://raw.githubusercontent.com/brendenthebanana-hash/OsuSkinners/master/install.sh | SKINMAKER_BRANCH=master sh

This installs into your home folder: the program, a `skinmaker` command, and an app menu
entry with an icon. If `skinmaker` is not found, add `export PATH="$HOME/.local/bin:$PATH"`
to `~/.bashrc`.

## Use

Open **osu! Skin Maker** from your app menu (or run `skinmaker`).

- **Live preview** of circles, approach circle, followpoints, slider (ball, follow circle, ticks,
  reverse arrow), spinner, cursor + trail, score/combo font and hit results, plus a cursor
  close-up and a font strip. The preview uses the same sprites that get exported.
- **Search** box filters all options. Changed options are highlighted and can be reset one by one,
  per group, or all at once. **Undo/Redo** (Ctrl+Z), **random colors / random styles**, and
  **Export / Import** of your settings as JSON.
- **Presets**: classic, neon, pastel, dark, sunset, mono, retro, candy, hex.
- **Hit sounds**: every sample (hit normal, clap, whistle, finish, slider tick, combo break,
  slider slide and whistle loops) is synthesized from waveform, pitch sweep, envelope, noise,
  distortion, filter, echo and more, with a Play button. Normal, soft and drum sets are written.
- **Global color adjust**: hue, saturation, brightness, contrast, grayscale, invert, tint.
- **Save to library** keeps skins with thumbnails. **Download .osk**, then open it with osu!
  (or drag it into the game window). Building takes several seconds because it renders ~40
  images and ~24 sounds.

The app opens in its own window if a Chromium based browser (Chrome, Chromium, Brave, Edge,
Vivaldi, also Flatpak versions) is installed. Otherwise it opens in a browser tab; stop it with
Ctrl+C. Force a tab with `skinmaker --browser`.

## Command line

    skinmaker "My Skin" --preset neon --set cursor_shape=arrow --set circle_glow=true
    skinmaker --list-options
    skinmaker "My Skin" --config exported-settings.json

## Uninstall

    sh uninstall.sh
