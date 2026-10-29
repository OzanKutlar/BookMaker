# bookpdf

Turns the chapters saved by the Book Translator CLI into print-ready PDFs, one per arc or volume.

- Reads the translator's book folders and never modifies chapter files.
- Shows each book's arcs/volumes from `Arcs.json` (recorded by the translator or defined here).
- Converts the Markdown chapters to LaTeX and compiles them with Tectonic (or TeX Live) behind live progress bars.
- Every PDF numbers its chapters from 1, like a real hardcover volume. Afterwords print without a number.

## Setup

1. Python 3.10 or newer, then:

        pip install -r requirements.txt

2. A TeX engine. Tectonic is recommended: a single program instead of a multi-gigabyte install.

### Installing Tectonic (Windows)

1. Open https://github.com/tectonic-typesetting/tectonic/releases and pick the newest release that lists downloadable files (tags look like `tectonic@0.15.0`).
2. Download the file ending in `x86_64-pc-windows-msvc.zip`.
3. Extract `tectonic.exe` next to `bookpdf.py`. bookpdf looks there automatically, so no PATH changes are needed.
4. Check that it works:

        .\tectonic.exe --version

The first build downloads the TeX packages and fonts it needs, so it needs internet and takes longer. Later builds reuse the cache.

Mac: `brew install tectonic`. Linux: see https://tectonic-typesetting.github.io for the installer.

### Using TeX Live instead

Install TeX Live (full) or MacTeX and make sure `xelatex` and `latexmk` work in a terminal. bookpdf uses them when Tectonic isn't found, or when you pass `--engine latexmk`.

## Usage

    python bookpdf.py -l "C:\path\to\TranslateBook"

1. Pick a book.
2. The first time, enter the book name and author for the title page.
3. If the book has no arcs yet, enter the last chapter of each arc/volume (for example 2000, then 3000) and a name for each. `rest` puts every remaining chapter in a final arc; Enter or `done` stops.
4. From the menu: build one arc, run a quick **Test build** (first 5 chapters), build all arcs, define more arcs, redefine them (the old file is kept as `Arcs.json.bak`), or edit the book name/author.

Finished PDFs go to `output/<Book> - <Arc>.pdf`.

### Options

| Option | Default | Meaning |
|---|---|---|
| `-l`, `--library` | `../TranslateBook` | Folder containing your book folders |
| `-b`, `--book` | | Open this book directly |
| `--engine` | `auto` | `tectonic`, `latexmk`, or `auto` (Tectonic first) |
| `--cjk-font` | FandolSong | Chinese font: a font file (`.otf`/`.ttf`/`.ttc`) or an installed font name |
| `--output` | `output` | Where finished PDFs go |
| `--build-dir` | `build` | Temporary build files |
| `--keep-build` | off | Keep the build folder after a successful build |
| `--timeout` | `180` | Minutes before a build is stopped |
| `--log-lines` | `8` | Engine output lines shown live under the progress bar (0 hides them) |
| `--density` | `tight` | Table of contents layout: `tight` (3 columns, titles cut at 30 characters) or `loose` (2 columns, 50 characters) |
| `--toc-title-length` | per density | Cut TOC titles after this many characters (10–200); `0` never cuts |

## How a build works

1. **Convert.** Each chapter becomes `build/<book>/<arc>/chapters/ch-0001.tex`, and so on, with a progress bar. The `# Chapter N: Title` heading becomes the chapter title, `[[Chapter N]]` links are removed, and `(TN: ...)` paragraphs are set small and italic. A chapter that fails to convert is listed and skipped.
2. **Compile.** The bar counts typeset pages. Pass 1 shows an estimated total; later passes know the exact page count. "last output Ns ago" resets whenever the engine prints something and turns yellow after a minute of silence, which is how you tell a slow build from a stuck one. The last few lines of the engine's own output scroll underneath the bar, Docker-style, and collapse into a summary line when the build finishes. Before the first page is typeset (for example while Tectonic downloads its files on the first run) the bar pulses and counts downloaded files.
3. **Output.** The PDF is copied to `output/` and the build folder is deleted (unless `--keep-build`). On failure the folder is kept, and the error panel names the chapter `.md` file that broke the build plus the full `build.log`.

## Table of contents

The table of contents is set small and in several columns, so even a 1,000+ chapter volume needs only a few pages. The chapter-number column is sized to the biggest chapter number in each PDF, so 4- and 5-digit numbers never run into the titles. Long titles are cut at a word boundary and end with `…`, but only in the contents: the chapter heading and the PDF bookmark keep the full title.

    python bookpdf.py --density loose --toc-title-length 60

## Chinese font

The default Chinese font is FandolSong, which ships with TeX Live and Tectonic. To use another font, pass a font file:

    python bookpdf.py --cjk-font "C:\Fonts\NotoSerifSC-Regular.otf"

The file is copied into each build, so it doesn't need to be installed.

## Arcs.json

Same file and format as the translator (`<Book>/Arcs.json`). Each arc stores its last chapter; it starts one chapter after the previous arc. Arcs you define here are marked `"source": "user"`, and the translator never moves them.
