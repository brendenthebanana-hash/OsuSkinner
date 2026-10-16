#!/bin/sh
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
rm -rf "$DATA/osu-skinmaker" "$HOME/.local/bin/skinmaker" "$DATA/applications/osu-skinmaker.desktop" \
       "$DATA/icons/hicolor/256x256/apps/osu-skinmaker.png"
echo "Removed osu! Skin Maker. (Saved skins were in $DATA/osu-skinmaker/skins and are gone too.)"
