# AgentMem, brand kit v1 (brace brain)

Mark: brain in profile; the central sulcus between the hemispheres is a pair of
curly braces `{ }`. Two faint gyri above it = memories fading; the brace fold is
the one that stays. Memory wraps the session.

## Files
| File | Use |
|---|---|
| `mark-ink.svg` / `mark-blue.svg` / `mark-white.svg` | primary mark, sạch, không chi tiết thừa |
|
| `mark-bold.svg` | heavy stroke, small sizes, terminal glyph, stickers |
| `mark-knockout.svg` | solid brain, braces knocked out, dark backgrounds |
| `icon-tile-{ink,blue,light}.svg` | app icon, GitHub avatar, Docker |
| `favicon-tile.svg` + `favicon-{16,32,48}.png` | favicon (tile version survives 16px) |
| `apple-touch-icon.png` (180) · `icon-192.png` · `icon-512.png` | PWA / mobile |
| `lockup-*.svg` | horizontal lockup with wordmark |

## Colors
- Ink `#17171A`, primary
- Blue `#3B5BDB`, accent
- Paper `#FFFFFF`, knockout

## Rules
- Clear space around the mark = height of one brace.
- Never stretch; never add a gradient inside the brain; never rotate.
- Below 32px use `mark-bold` or the favicon tile, thin strokes break up.

## TODO before public launch
- Wordmark in `lockup-*.svg` still references a system font, convert text to
  outlines (Illustrator/Inkscape: Path > Object to Path) so it renders
  identically everywhere.
- Optional: hand-smooth the brain outline on a grid; current path is a clean
  draft but a designer pass would tighten the bumps.

## PNG exports
- `mark-{ink,blue,white}-{256,512,1024}.png`, nền trong suốt
- `lockup-{ink,blue,white}-{1200,2400}.png`, nền trong suốt
- `lockup-ink-singular-*.png`, bản tagline số ít "FOR AGENT"
- `icon-tile-{ink,blue,light}-{512,1024}.png`, app icon
- `favicon-{16,32,48}.png`, `apple-touch-icon.png`, `icon-{192,512}.png`
