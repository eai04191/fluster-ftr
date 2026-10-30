# The FTR (Fluster) animation format in Windows Vista

This documents the `FTR` resources in Windows Vista's `shell32.dll` and `shellstyle.dll`: the file-operation header animations and the Explorer "Flare". It was worked out from the Japanese Vista SP2 x86 DVD (`shell32.dll` PDB GUID `01C50E63-82DD-4CF0-A9CA-63D04A60159F`, age 2) by disassembling the engine with Microsoft's public symbols. All eight FTR resources in that build parse exactly to their last byte with the layout below.

## Where it lives

- Engine: `windows\advcore\duser\directui\fluster` (`fluster.lib`), C++ namespace `SWF`, statically linked into `shell32.dll`. `shellstyle.dll` contains only resources.
- Host: the DirectUI `<movie>` element (`DirectUI::Movie`), for example in `shell32.dll` UIFILE #42 (the progress dialog):
  `<movie id="atom(headeranimation)" height="40rp" width="400rp" SmoothingMode="high" repeat="true" AutoStart="false" AutoStop="false" layoutpos="right"/>`
- `CProgressDialogUI::_AnimationFromAction` picks the resource from a table indexed by `SPACTION`:

| FTR | SPACTION |
| --- | --- |
| 200 | NONE, DOWNLOADING, SEARCHING_INTERNET, CALCULATING, UPLOADING, SEARCHING_FILES, RENAMING, FORMATTING |
| 201 | COPYING |
| 202 | MOVING |
| 203 | APPLYINGATTRIBS |
| 204 | RECYCLING |
| 205 | DELETING |

`shellstyle.dll` FTR 200 and 201 are Flare variants (273.6×144 px, 30 fps).

## What it is

FTR is not SWF bytes. Fluster has two readers: `parse()` reads real SWF (bit-packed RECT, SHAPERECORD, zlib), and `read()` deserializes Fluster's own object graph, which `write()` produced at build time. FTR is the `read()` form: SWF tags already converted to GDI+ objects (pens, brushes, flattened `GraphicsPath` point arrays). Everything is little-endian and byte-aligned. There is no header magic or version field.

## Primitives

| Name | Layout |
| --- | --- |
| `u8`, `u16`, `u32`, `i32` | little-endian integers |
| `f32`, `f64` | IEEE floats |
| `Color` | `u8 R, u8 G, u8 B, u8 A` (passed to `Color::MakeARGB(A,R,G,B)`) |
| `Matrix` | `f32 m11, m12, m21, m22, dx, dy` (`Gdiplus::Matrix`; `x' = x*m11 + y*m21 + dx`, `y' = x*m12 + y*m22 + dy`) |
| `List<T>` | `u32 count`, then `count` × `T` |

All coordinates are twips (1/20 px).

## File

```
i32 x, y, width, height   // movie bounds in twips (header: 0,0,8000,800 = 400×40 px)
f64 fps                   // 24.0 for the headers, 30.0 for the Flare
List<Tag> tags
```

## Tags

Each tag is `u32 id` followed by its body (`SWF::TagFactory::read`, `SWF::make`). The IDs are SWF tag codes.

| id | Class | Body |
| --- | --- | --- |
| 1 | ShowFrame | none |
| 2, 22, 32 | DefineShape (all three IDs build the same class) | `u16 characterId`, `Shape` |
| 9 | SetBackgroundColor | `Color` |
| 10 | DefineFont | not used by these files; layout not documented here |
| 11 | DefineText | not used by these files; layout not documented here |
| 12 | DoAction | `u32 action`, `u16 frame` |
| 26 | PlaceObject2 | see below |
| 28 | RemoveObject2 | `u16 depth` |
| 39 | DefineSprite | `u16 characterId`, `List<Tag>` (the sprite's own timeline) |

Any other ID fails to load.

### Shape

```
List<Pen>          pens      // Pen = Color, f32 width (twips); both caps LineCapRound
List<Brush>        brushes
List<Path>         paths
List<Action>       actions   // Action = u32 type, i32 index
```

`Path` is `List<{ f32 x, f32 y, u8 type }>`, passed straight to `GraphicsPath(points, types, count, FillModeAlternate)`. Types are GDI+ `PathPointType`: 0 start, 1 line, 3 cubic Bézier (three consecutive points), with the 0x80 close flag. Only 0, 1 and 3 appear in Vista's files.

`Action` drives drawing (`Shape::render`):

| type | Meaning |
| --- | --- |
| 0 | select pen `index` (−1 = none) |
| 1 | select brush `index` (−1 = none) |
| 2 | draw path `index`: `FillPath` with the current brush, then `DrawPath` with the current pen |

### Brush

`u32 type` uses GDI+ `BrushType` numbering:

| type | Body | Construction |
| --- | --- | --- |
| 0 SolidColor | `Color` | `SolidBrush` |
| 2 TextureFill | `Image`, `u32 WrapMode`, `Matrix` | `TextureBrush` (not used by these files) |
| 3 PathGradient | `List<{Color, f32 position}>`, `Matrix` | `PathGradientBrush` over the ellipse (−16384, −16384, 32768, 32768); `SetInterpolationColors`; `SetTransform` |
| 4 LinearGradient | `List<{Color, f32 position}>`, `Matrix` | `LinearGradientBrush((−16384,0), (16384,0))`, `WrapModeTileFlipXY`; `SetInterpolationColors`; `SetTransform` |

Gamma correction is off for both gradients. At most 10 stops are read. For PathGradient, GDI+ measures positions from the boundary (0) to the center (1), and nothing is painted outside the ellipse.

### PlaceObject2

```
u8  hasClipDepth
u8  hasColorTransform
u8  hasMatrix
u8  hasCharacter
u8  (unused by execute; mostly 1)
u16 depth
u16 characterId
u16 clipDepth
Matrix                   if hasMatrix
ColorTransform           if hasColorTransform
```

`ColorTransform` is eight `f32`: `mulR, addR, mulG, addG, mulB, addB, mulA, addA`. They fill the diagonal and the translation row of an identity `ColorMatrix`. Adds are on the 0–255 scale.

## Playback (`SWF::Movie`)

Definitions (DefineShape, DefineSprite) go into a global table by character ID. Every other tag is a command appended to the root timeline, or to the sprite's timeline when nested. Each timeline has a command index and four per-depth arrays: character, matrix, color transform, clip depth.

`advanceFrame(paused, loop)`, called once per frame:

1. If not paused: if the index is 0, clear the display list. Then run commands from the index. Before each command, advance the index, or wrap it to 0 when it is the last command and `loop` is set. Stop after the first command that returns false. Only ShowFrame returns false.
2. Then, for each depth in order, if the character is a sprite, call its timeline's `advanceFrame(false, loop)`.

Command effects:

- PlaceObject2: look up the character by ID if `hasCharacter`, otherwise the one already at `depth`; do nothing if there is none. With `hasCharacter`, clear the depth's character and clip, then set the character. Matrix and color transform are kept unless the tag supplies new ones. Then set the matrix, color transform and clip depth when present.
- RemoveObject2: clear the depth's character and clip depth. Matrix and color transform stay.
- DoAction: action 1 clears the display list and advances `frame + 1` times. Action 0 does nothing (Flare 201 has one).
- SetBackgroundColor: stored, never painted by `SWF::render`.

Sprite state belongs to the definition, not to the placement. A sprite placed twice shares one timeline, which advances once per placement. Placing a sprite again does not restart it.

## Rendering (`Movie::render`, `renderDepth`, `removeMasks`)

- Screen transform: scale the bounds rect onto the element, so twips map to pixels at 1/20.
- For each depth in ascending order, prepend the depth's matrix (`MatrixOrderPrepend`).
- If the depth has a clip depth and its character is a shape, it is a mask and is not drawn. Its draw-action paths are combined into one `GraphicsPath` (FillModeAlternate) and passed to `SetClip`: `CombineModeReplace` when no other mask is active in this timeline, `CombineModeIntersect` otherwise. Its range ends at `clipDepth`.
- After each depth, ranges ending at or below it are dropped. If any were dropped, the clip is reset to infinite and the remaining masks are applied again. The clip is a single `Graphics` state, so a nested sprite's masks can replace the parent's clip.
- Color transforms compose as `ColorMatrix(parent) × ColorMatrix(child)` in GDI+'s row-vector convention: the parent's transform is applied first, then the child's. Each color becomes `clamp(c × mul + add)`, truncated to 0–255, and is applied to pen colors, solid colors and every gradient stop before drawing.

## Not verified

- The look was not compared side by side with a real Vista machine. The player follows the disassembly above.
- The exact meaning of DirectUI `Gradient(..., 3)` in the progress dialog header (`argb(255,9,74,116)`, `argb(255,32,121,140)`, `argb(255,5,111,90)`) was not traced. The player draws it as a left-to-right three-stop gradient.
- Windows 7's `shell32.dll` was not examined.
