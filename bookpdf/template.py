"""XeLaTeX version of the hand-made main.tex; placeholders are filled per build."""

from dataclasses import dataclass

from .convert import latex_escape

# FandolSong ships with TeX Live and Tectonic's bundle; FandolKai is used for italic Chinese in TNs.
DEFAULT_CJK_FONT = (
    r"\setCJKmainfont[BoldFont=FandolSong-Bold.otf, ItalicFont=FandolKai-Regular.otf]{FandolSong-Regular.otf}"
)


# Must not share a base name with the chapters/ folder: \input tries the bare name first,
# and on Windows opening a folder as a file fails with "Access is denied".
MANIFEST_NAME = "chapter-list.tex"


@dataclass(frozen=True)
class TocLayout:
    """How densely the table of contents is set."""
    columns: int           # columns side by side (2-4)
    font_pt: float         # entry font size
    leading_pt: float      # distance between entry baselines
    title_length: int      # default TOC title cut-off in characters (0 = never cut)
    entries_per_page: int  # rough capacity, only used for the pass-1 page estimate


TOC_LAYOUTS = {
    "tight": TocLayout(columns=3, font_pt=7.5, leading_pt=9, title_length=30, entries_per_page=210),
    "loose": TocLayout(columns=2, font_pt=8, leading_pt=9.5, title_length=50, entries_per_page=130),
}
DEFAULT_DENSITY = "tight"
MIN_TOC_COLUMNS = 2
MAX_TOC_COLUMNS = 4


def cjk_font_by_name(name: str) -> str:
    return r"\setCJKmainfont{" + name + "}"


def cjk_font_from_file(filename: str) -> str:
    return r"\setCJKmainfont[Path=./fonts/]{" + filename + "}"


MAIN_TEMPLATE = r"""\documentclass[14pt, a4paper]{extarticle}

% ==========================================
% 1. FONTS & PLUGINS (XeLaTeX / Tectonic)
% ==========================================
\usepackage{fontspec}
\setmainfont[
  Extension      = .otf,
  UprightFont    = *-regular,
  BoldFont       = *-bold,
  ItalicFont     = *-italic,
  BoldItalicFont = *-bolditalic
]{texgyretermes}            % TeX Gyre Termes: a Times New Roman clone
\usepackage{xeCJK}          % Chinese characters (names, translator's notes)
<<CJK_FONT>>
% Keep curly quotes, dashes and ellipses in the Latin font (xeCJK would set them full-width)
\xeCJKDeclareCharClass{Default}{"2014, "2018, "2019, "201C, "201D, "2026}
\usepackage{microtype}      % Typographical alignment
\usepackage{setspace}       % Line spacing
\usepackage{titlesec}       % Section title formatting
\usepackage{multicol}       % Multi-column layouts for TOC
\usepackage{csquotes}       % Markdown block quotes
\usepackage[normalem]{ulem} % Markdown strikethrough
\usepackage[hidelinks]{hyperref} % Clickable / traversable links without ugly boxes

% ==========================================
% 2. PAGE LAYOUT, MARGINS & HEADERS
% ==========================================
\usepackage[left=3cm, right=2cm, top=3cm, bottom=2cm, includehead, headheight=1.5cm]{geometry}

\usepackage{fancyhdr}
\pagestyle{fancy}
\fancyhf{}
\renewcommand{\headrulewidth}{0pt}
\fancyhead[R]{\thepage}
\setlength{\headsep}{0.5cm}

% ==========================================
% 3. LINE SPACING AND PARAGRAPHS
% ==========================================
\setlength{\parindent}{1cm}
\setlength{\parskip}{10pt}
% Let TeX stretch a tight line a little rather than push text into the right margin
\setlength{\emergencystretch}{3em}

% ==========================================
% 4. SECTION/CHAPTER FORMATTING
% ==========================================
\newcommand{\sectionbreak}{\clearpage}
\renewcommand{\thesection}{\arabic{section}}

\titleformat{\section}[block]
  {\normalfont\fontsize{20}{17}\bfseries\centering}
  {\thesection \ \ }
  {0pt}
  {\MakeUppercase}
\titlespacing*{\section}{0pt}{1.5\baselineskip}{1.5\baselineskip}

% ==========================================
% 5. TABLE OF CONTENTS
% ==========================================
% Entries are normal weight with dotted leaders and no extra space between them.
% \tocnumwidth is measured in the TOC font for each build, so 4- and 5-digit
% chapter numbers never run into their titles.
\newlength{\tocnumwidth}
\makeatletter
\renewcommand*{\l@section}{\@dottedtocline{1}{0pt}{\tocnumwidth}}
\renewcommand*{\@pnumwidth}{2.6em} % room for 5-digit page numbers
\renewcommand*{\@tocrmarg}{3.2em}
\renewcommand*{\@dotsep}{3}
\newcommand{\booktoc}{\@starttoc{toc}} % TOC entries without the built-in heading
\makeatother

% ==========================================
% BOOK METADATA (filled in by bookpdf)
% ==========================================
\title{\textbf{<<TITLE>>}}
\author{\parbox{0.9\textwidth}{\centering <<AUTHOR>>}} % long author names wrap instead of overflowing
\date{\today}

% ==========================================
% DOCUMENT ENVIRONMENT
% ==========================================

\newcommand{\tnote}[1]{{\footnotesize\itshape #1\par}}
\begin{document}

\maketitle

\clearpage

% Compact, multi-column, traversable Table of Contents.
% The heading sits above the columns so it spans the page instead of filling column one.
{\centering\fontsize{14}{17}\selectfont\bfseries TABLE OF CONTENTS\par}
\vspace{1.5\baselineskip}
{
  \setlength{\parskip}{0pt}
  \setlength{\columnsep}{12pt}
  <<TOC_FONT>>
  \settowidth{\tocnumwidth}{<<TOC_NUMBER_SAMPLE>>\enspace}
  \begin{multicols}{<<TOC_COLUMNS>>}
    \raggedcolumns
    \booktoc
  \end{multicols}
}

\clearpage

% ==========================================
% CHAPTERS: the chapter list is written by bookpdf for this arc
% ==========================================
\input{<<MANIFEST>>}

\end{document}
"""


def _number_sample(highest_number: int) -> str:
    """A run of zeros as wide as the biggest chapter number; it sizes the TOC number column."""
    return "0" * len(str(max(int(highest_number), 1)))


def _toc_font(layout: TocLayout) -> str:
    return r"\fontsize{" + f"{layout.font_pt:g}" + "}{" + f"{layout.leading_pt:g}" + r"}\selectfont"


def _check_layout(layout: TocLayout) -> None:
    if not MIN_TOC_COLUMNS <= layout.columns <= MAX_TOC_COLUMNS:
        raise ValueError(f"TOC columns must be {MIN_TOC_COLUMNS}-{MAX_TOC_COLUMNS}, got {layout.columns}")
    if layout.font_pt <= 0 or layout.leading_pt < layout.font_pt:
        raise ValueError("TOC font size must be positive and no larger than its leading")


def render_main(title: str, author: str, cjk_setup: str, layout: TocLayout, highest_number: int) -> str:
    _check_layout(layout)
    return (
        MAIN_TEMPLATE
        .replace("<<MANIFEST>>", MANIFEST_NAME)
        .replace("<<CJK_FONT>>", cjk_setup)
        .replace("<<TOC_FONT>>", _toc_font(layout))
        .replace("<<TOC_COLUMNS>>", str(layout.columns))
        .replace("<<TOC_NUMBER_SAMPLE>>", _number_sample(highest_number))
        .replace("<<TITLE>>", latex_escape(title))
        .replace("<<AUTHOR>>", latex_escape(author))
    )
