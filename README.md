# Fluster FTR

The animated header of Windows Vista's file copy dialog and the "Flare" in Explorer's details pane are not videos. They are vector animations in a Microsoft format called FTR, played by **Fluster**, a small SWF-derived engine linked into `shell32.dll`. As far as we could find, no public tool could read the format before this: a [JPEXS feature request](https://www.free-decompiler.com/flash/issues/2495-add-support-for-fluster-ftr-files-and-exporting-support) for it is still open, and the [BetaArchive thread](https://www.betaarchive.com/forum/viewtopic.php?t=26468) asking how these animations work dates back to 2012.

This repository contains:

- [`index.html`](index.html): a browser player. Drop `shell32.dll`, `shellstyle.dll` or an extracted `.ftr` file onto it. Everything runs locally; nothing is uploaded.
- [`FORMAT.md`](FORMAT.md): the format specification, including playback and rendering rules.
- [`tools/ftr.py`](tools/ftr.py): a command-line parser and extractor (Python 3, standard library only).
- [`tools/pdb_publics.py`](tools/pdb_publics.py): lists the public symbols from Microsoft's PDB at addresses that match the shipped DLL, so the claims in `FORMAT.md` can be checked in any disassembler.

No Microsoft binaries or animation data are included. You need your own copy of Windows Vista.

## The animations

| Resource | Shown for |
| --- | --- |
| `shell32.dll` FTR 200 | everything without its own animation: calculating, downloading, searching, renaming, … |
| `shell32.dll` FTR 201 | copying |
| `shell32.dll` FTR 202 | moving |
| `shell32.dll` FTR 203 | applying properties |
| `shell32.dll` FTR 204 | moving to the Recycle Bin |
| `shell32.dll` FTR 205 | deleting |
| `shellstyle.dll` FTR 200, 201 | the Explorer Flare |

The header animations are 400×40 px at 24 fps and loop. The Flare is 273.6×144 px at 30 fps.

## Getting the DLLs

From a Windows Vista installation, copy `C:\Windows\System32\shell32.dll` and `C:\Windows\System32\shellstyle.dll`.

From Vista install media, the files are inside `sources/install.wim`. With 7-Zip:

```sh
7z e Vista.iso sources/install.wim
7z e install.wim 1/Windows/System32/shell32.dll 1/Windows/System32/shellstyle.dll
```

## Player

Open `index.html` in a current Chrome, Edge, Firefox or Safari, or serve the repository with GitHub Pages. Drop one or more files. Each FTR resource gets a button. The player can step frame by frame, scrub, loop, zoom, switch backgrounds, and save a PNG of the current frame or a WebM of one loop.

## Command line

```sh
python3 tools/ftr.py info shell32.dll shellstyle.dll    # one line per animation
python3 tools/ftr.py extract shell32.dll out/           # write out/shell32_200.ftr ...
python3 tools/ftr.py json shell32.dll 201 > copy.json   # full parse as JSON
```

## How this was worked out

The analysis used the Japanese Windows Vista SP2 x86 DVD. Microsoft's symbol server still serves the public `shell32.pdb` for that build, and it names the engine outright: `SWF::Fluster`, `SWF::Movie`, `SWF::TagFactory`, `SWF::Shape`, and object files under `windows\advcore\duser\directui\fluster`. Vista's DLLs were rearranged by BBT after linking, so the PDB addresses only line up after mapping them through the PDB's OMAP stream (`tools/pdb_publics.py` does this).

Fluster has two loaders. `parse()` reads genuine SWF. `read()` reads Fluster's own serialization of already-converted GDI+ objects: pens, brushes and `GraphicsPath` point arrays. FTR is the `read()` form. Disassembling `SWF::SWF::read`, every `Tag::read`, `Shape::render`, `Movie::advanceFrame` and `Movie::render` gave the layout and the playback rules in `FORMAT.md`. Where Fluster differs from Flash, the player follows Fluster: the order in which color transforms compose, path-gradient stop direction, sprite state shared per definition, and masks as one global GDI+ clip. All eight FTR resources in Vista SP2 parse to their last byte.

The reverse engineering and the code were done with the help of Claude (Anthropic).

## Limitations

- The rendering follows the disassembly but has not been compared frame by frame against a real Vista machine.
- Only Vista SP2 x86 was examined. Windows 7 has not been checked.
- `DefineFont`, `DefineText` and texture brushes exist in the engine but appear in none of Vista's files, so they are not implemented.
- The progress-dialog background is approximated as a three-color horizontal gradient.

## License

[CC0 1.0](LICENSE): dedicated to the public domain. Use, copy, modify and redistribute any of it, for any purpose, without asking or crediting. Windows, its DLLs and the animations inside them remain Microsoft's and are not covered.
