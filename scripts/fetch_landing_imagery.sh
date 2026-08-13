#!/usr/bin/env bash
#
# Rebuilds the landing page's ghost imagery in frontend/public/landing/.
#
# The output is committed, so this is not part of any build — it exists because
# a directory of eight opaque JPEGs is otherwise a set of files nobody can trace
# back to a source or a licence. Run it to change a picture or to re-derive the
# whole set; CREDITS.md is written from the same API response that produced the
# bytes, so the attribution cannot drift away from what actually shipped.
#
# The pictures land on the page at partial opacity inside a hairline frame, so
# they are downsized hard: nothing here is ever painted wider than 420 CSS px,
# and the difference between shipping the originals and shipping these is a
# megabyte and a half on a page whose whole point is that it starts moving
# immediately.
#
# macOS only — `sips` is the one image tool this machine has (no cwebp, no
# ImageMagick), which is also why these are JPEG rather than WebP.
#
# Usage: scripts/fetch_landing_imagery.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$REPO_ROOT/frontend/public/landing"
API="https://commons.wikimedia.org/w/api.php"
UA="oracle-x-landing-imagery/1.0 (https://github.com/Yigtwxx)"

# Sized by width, not by long edge: the figure box is driven by `width:
# clamp(260px, 27vw, 420px)` and takes whatever height the aspect ratio gives
# it, so width is the only dimension that decides how much detail is actually
# resolvable. 720 covers the 420px maximum at over 1.7x.
#
# MAX_HEIGHT then catches the portraits, which would otherwise come back as
# 1500px-tall files to serve a box that is never taller than about 900. Applied
# second so it only ever shrinks further, never upscales.
TARGET_WIDTH=720
MAX_HEIGHT=1000

# Keys cropped to a tall 2:3 frame before anything else happens to them.
#
# A column of upright pictures reads as a set; a mix of landscape and portrait
# reads as whatever each photographer happened to shoot. The two exceptions are
# the portraits of people, which are already upright and would end up cropped
# into the face.
PORTRAIT_KEYS=" print ai live heatmap macro "
PORTRAIT_MAX_H=900
# Higher than the greyscale set needed. These are now in colour and painted at
# roughly 45% rather than 16%, so JPEG ringing around a hard edge is actually
# reachable — q40 was free when the picture was a faint grey smudge and is not
# any more.
JPEG_QUALITY=48

# stage-key | source | one-line note for CREDITS.md
#
# `source` is either a Commons file title, in which case the URL, licence and
# author are resolved from the API, or a direct https:// URL followed by its
# credit after a `##` — the escape hatch for the one picture Commons does not
# have. Kept as one table rather than parallel arrays so a picture can be
# swapped by editing a single line. The stage key is the output filename and
# must match a key in frontend/lib/landing/imagery.ts.
#
# On subject choice: present tense, not archive. An earlier set ran on period
# photographs — the ENIAC, a 1960s exchange floor, a Victorian painting of the
# Pythia — and the page read as a museum wall rather than as a terminal for a
# market that is open right now. Every entry is a thing that exists today.
#
# Each also has to survive being painted at low opacity next to a moving chart,
# which rules out more than it sounds like: crowds turn to noise below about
# 400px, and anything dominated by green or red starts arguing with the candles.
# What works is one high-contrast subject with mid-tone texture.
#
# The Unsplash entries carry no attribution requirement; the credits below are
# courtesy. The Commons entries are the three subjects Unsplash cannot supply,
# because they are specific people and places rather than stock situations.
FIGURES=(
  "print|NASDAQ MarketWatch (48105831361).jpg|The Nasdaq MarketSite in Times Square — where the tape is a building."
  "ai|https://images.unsplash.com/photo-1555618254-84e2cf498b01?fm=jpg&q=85&w=1400&fit=max##Christian Wiediger · Unsplash License · https://unsplash.com/photos/3GUW88tRmv8|The card every model on this page is eventually run on."
  # Not a picture of chat. A phone running a chatbot was the literal reading and
  # it looked like a press release; the facade is the thing being asked about.
  "chat|https://images.unsplash.com/photo-1783691501257-74b89368ba43?fm=jpg&q=85&w=1400&fit=max##Cara Willenbrock · Unsplash License · https://unsplash.com/photos/I1DlCNUpyr0|The NYSE facade, with its name still carved into it."
  # Commons has no usable close-up of Charging Bull: the sculpture is still in
  # copyright and the US has no freedom of panorama, so the tight shots get
  # deleted and only wide streetscapes survive — in which the bull is a speck.
  # Whole animal, not a detail. A tight crop of the head was unreadable at this
  # size — it needs the street around it to be recognisably the Bowling Green
  # bull rather than a piece of bronze.
  "live|https://images.unsplash.com/photo-1689582236730-fa3076847f45?fm=jpg&q=85&w=1400&fit=max##Harri P · Unsplash License · https://unsplash.com/photos/ZQZMJ0y7FDo|Charging Bull at Bowling Green, barriers and all."
  # The one picture here that is not stock or public domain: a press photo of
  # the NYSE floor on the day Martı listed, Turkish flags on the wall screens.
  # Chosen by the project owner, who has been told what it is. The two attempts
  # before it were a synthetic-looking trading desk and an unreadable quote
  # board; this is the only one of the three that is both real and legible.
  "heatmap|https://n24.com.tr/varliklar/img/yuklemeler/image_870x580_666984fc73ded.jpg##Press photo via n24.com.tr — rights not cleared, used at the project owner's direction · https://n24.com.tr/en/turkish-ride-sharing-firm-marti-celebrated-at-the-new-york-stock-exchange-with-turkish-flag|The NYSE floor the day Martı listed, under a wall of Turkish flags."
  "macro|Europäische Zentralbank Frankfurt.jpg|The ECB tower in Frankfurt — the building rates come out of."
  "ownership|Warren Buffett at the 2015 SelectUSA Investment Summit.jpg|Buffett — the register read as an argument, quarter after quarter."
  # Trump sat on `macro` until the ECB took it, and he is not a downgrade here:
  # the community stage is about a thesis argued in public and defended in the
  # replies, and there is no larger working example of that in the world.
  "social|Official Presidential Portrait of President Donald J. Trump (2025).jpg|A thesis argued in the open, at volume."
)

command -v sips >/dev/null || { echo "sips not found — this script is macOS only." >&2; exit 1; }

# Shrink and re-encode. Shrinking is guarded in both dimensions because
# `--resampleWidth` will happily upscale a narrower source, which is worse than
# useless — the ticker photo is only 640px wide to begin with.
#
# Colour is kept. An earlier pass converted these to greyscale on the theory
# that a page whose palette is entirely semantic could not afford eight
# photographs bringing their own hues; in place it read as archive footage
# rather than as pictures, so they now ship in colour and the framing does the
# work of separating them from the tape.

# The portrait crop is adaptive rather than a fixed 600x900, because the sources
# do not all have 900px of height to give — the press photo of the Martı listing
# is 580 tall, and cropping it to a fixed frame would mean upscaling it by half
# to throw away the sides. This takes the tallest 2:3 rectangle each source can
# actually supply, so nothing is ever enlarged.
crop_portrait() {
  local file="$1" w h th tw
  w="$(sips -g pixelWidth "$file" | awk '/pixelWidth/ {print $2}')"
  h="$(sips -g pixelHeight "$file" | awk '/pixelHeight/ {print $2}')"

  th="$h"
  if [ "$th" -gt "$PORTRAIT_MAX_H" ]; then th="$PORTRAIT_MAX_H"; fi
  tw=$(( th * 2 / 3 ))
  if [ "$tw" -gt "$w" ]; then
    tw="$w"
    th=$(( w * 3 / 2 ))
    if [ "$th" -gt "$h" ]; then th="$h"; fi
  fi

  # `sips -c` is height then width, and crops from the centre.
  sips -c "$th" "$tw" "$file" --out "$file" >/dev/null
}

process() {
  local file="$1" key="$2" w h

  case "$PORTRAIT_KEYS" in
    *" $key "*) crop_portrait "$file" ;;
  esac

  # Full `if` rather than `[ ... ] && sips ...`: under `set -e` a false test at
  # the head of an && list takes the whole script down with it.
  w="$(sips -g pixelWidth "$file" | awk '/pixelWidth/ {print $2}')"
  if [ "$w" -gt "$TARGET_WIDTH" ]; then
    sips --resampleWidth "$TARGET_WIDTH" "$file" --out "$file" >/dev/null
  fi
  h="$(sips -g pixelHeight "$file" | awk '/pixelHeight/ {print $2}')"
  if [ "$h" -gt "$MAX_HEIGHT" ]; then
    sips --resampleHeight "$MAX_HEIGHT" "$file" --out "$file" >/dev/null
  fi
  sips -s format jpeg -s formatOptions "$JPEG_QUALITY" "$file" --out "$file" >/dev/null
}

mkdir -p "$OUT_DIR"

CREDITS="$OUT_DIR/CREDITS.md"
cat > "$CREDITS" <<HEADER
# Landing page imagery

Generated by \`scripts/fetch_landing_imagery.sh\` — do not edit by hand, and do
not add a file here without adding it to that script's table first.

Every file is capped at ${TARGET_WIDTH}px wide and ${MAX_HEIGHT}px tall and
re-encoded at JPEG quality ${JPEG_QUALITY}. The landing page paints them at
partial opacity inside a hairline frame, opposite the copy panel for their
stage, with the chart running behind them.

The CC BY and CC BY-SA entries below require attribution, which is what this
file is. Public-domain and Unsplash entries are listed for provenance rather
than obligation.

HEADER

for row in "${FIGURES[@]}"; do
  IFS='|' read -r key source note <<< "$row"
  echo "-> $key"

  if [[ "$source" == https://* ]]; then
    url="${source%%##*}"
    credit="${source#*##}"
    curl -sSL -A "$UA" -o "$OUT_DIR/$key.jpg" "$url"
    printf -- '- **`%s.jpg`** — %s  \n  %s\n' "$key" "$note" "$credit" >> "$CREDITS"
    process "$OUT_DIR/$key.jpg" "$key"
    continue
  fi

  title="$source"

  # One API call per file: the thumbnail URL, the licence and the author all
  # come back together, so the credit line is derived from the same response
  # that produced the bytes rather than from a hand-kept second list.
  meta="$(curl -sS -G "$API" -A "$UA" \
    --data-urlencode "action=query" \
    --data-urlencode "format=json" \
    --data-urlencode "prop=imageinfo" \
    --data-urlencode "iiprop=url|extmetadata" \
    --data-urlencode "iiurlwidth=1200" \
    --data-urlencode "titles=File:$title")"

  # One field per line, read one at a time: the licence and author strings
  # contain spaces, so a single space-splitting `read` would shred them.
  { read -r url; read -r page; read -r license; read -r author; } < <(
    printf '%s' "$meta" | python3 -c '
import html, json, re, sys

pages = json.load(sys.stdin)["query"]["pages"]
page = next(iter(pages.values()))
if "missing" in page:
    sys.exit("Commons file not found")
info = page["imageinfo"][0]
extra = info.get("extmetadata", {})


def field(name: str, fallback: str) -> str:
    raw = extra.get(name, {}).get("value", "") or fallback
    # extmetadata ships HTML; the credit line is plain text.
    text = re.sub(r"<[^>]+>", " ", html.unescape(raw))
    text = " ".join(text.split())
    # Commons often carries the same credit in two markup layers, which
    # collapses to "Unknown author Unknown author" once the tags are gone.
    half = len(text) // 2
    if text[:half].strip() == text[half:].strip():
        text = text[:half].strip()
    return text or fallback


for line in (
    info["thumburl"],
    info["descriptionurl"],
    field("LicenseShortName", "unknown"),
    field("Artist", "unknown"),
):
    print(line)
'
  )

  curl -sSL -A "$UA" -o "$OUT_DIR/$key.jpg" "$url"

  printf -- '- **`%s.jpg`** — %s  \n  %s · %s · [Commons](%s)\n' \
    "$key" "$note" "$author" "$license" "$page" >> "$CREDITS"

  process "$OUT_DIR/$key.jpg" "$key"
done

echo
du -ch "$OUT_DIR"/*.jpg | tail -1
