"""XeLaTeX version of the hand-made main.tex; placeholders are filled per build."""

from .convert import latex_escape

# FandolSong ships with TeX Live and Tectonic's bundle; FandolKai is used for italic Chinese in TNs.
DEFAULT_CJK_FONT = (
    r"\setCJKmainfont[BoldFont=FandolSong-Bold.otf, ItalicFont=FandolKai-Regular.otf]{FandolSong-Regular.otf}"
)


# Must not share a base name with the chapters/ folder: \input tries the bare name first,
# and on Windows opening a folder as a file fails with "Access is denied".
MANIFEST_NAME = "chapter-list.tex"


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

% Compact, two-column, traversable Table of Contents
\renewcommand{\contentsname}{\centering \fontsize{14}{17}\bfseries TABLE OF CONTENTS}
{
  \setlength{\parskip}{2pt} % Compact spacing between entries in TOC
  \begin{multicols}{2}
    \footnotesize
    \tableofcontents
  \end{multicols}
}

\clearpage

% ==========================================
% CHAPTERS: the chapter list is written by bookpdf for this arc
% ==========================================
\input{<<MANIFEST>>}

\end{document}
"""


def render_main(title: str, author: str, cjk_setup: str) -> str:
    return (
        MAIN_TEMPLATE
        .replace("<<MANIFEST>>", MANIFEST_NAME)
        .replace("<<CJK_FONT>>", cjk_setup)
        .replace("<<TITLE>>", latex_escape(title))
        .replace("<<AUTHOR>>", latex_escape(author))
    )
