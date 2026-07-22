"""Lightweight syntax highlighting used by Xyra's remote text editor."""

import os

from PyQt6.QtCore import QRegularExpression
from PyQt6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat


LANGUAGE_BY_EXTENSION = {
    ".py": "Python",
    ".pyw": "Python",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".jsx": "JavaScript",
    ".json": "JSON",
    ".jsonc": "JSON",
    ".html": "HTML",
    ".htm": "HTML",
    ".xml": "XML",
    ".svg": "XML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".sh": "Shell",
    ".bash": "Shell",
    ".ps1": "PowerShell",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".ini": "INI",
    ".cfg": "Config",
    ".conf": "Config",
    ".md": "Markdown",
    ".sql": "SQL",
}


def detect_language(path: str) -> str:
    name = os.path.basename(path or "").lower()
    if name in {"dockerfile", "containerfile"}:
        return "Dockerfile"
    if name in {"makefile", "gnumakefile"}:
        return "Makefile"
    if name.startswith(".") and "." not in name[1:]:
        return "Config"
    return LANGUAGE_BY_EXTENSION.get(os.path.splitext(name)[1], "Plain text")


def _format(color: str, *, bold: bool = False, italic: bool = False):
    text_format = QTextCharFormat()
    text_format.setForeground(QColor(color))
    if bold:
        text_format.setFontWeight(QFont.Weight.DemiBold)
    text_format.setFontItalic(italic)
    return text_format


class XyraSyntaxHighlighter(QSyntaxHighlighter):
    """A fast, intentionally conservative highlighter for common server files."""

    COMMON_KEYWORDS = {
        "Python": "and as assert async await break class continue def del elif else except False finally for from global if import in is lambda None nonlocal not or pass raise return True try while with yield",
        "JavaScript": "async await break case catch class const continue debugger default delete do else export extends false finally for function if import in instanceof let new null of return static super switch this throw true try typeof undefined var void while with yield",
        "TypeScript": "abstract any as async await boolean break case catch class const constructor continue declare default delete do else enum export extends false finally for from function if implements import in infer interface keyof let namespace never new null number object of private protected public readonly return static string super switch symbol this throw true try type typeof undefined unknown var void while yield",
        "C": "auto break case char const continue default do double else enum extern float for goto if inline int long register restrict return short signed sizeof static struct switch typedef union unsigned void volatile while",
        "C++": "alignas alignof auto bool break case catch char class const constexpr continue default delete do double else enum explicit export extern false float for friend if inline int long namespace new nullptr operator private protected public return short signed sizeof static struct switch template this throw true try typedef typename union unsigned using virtual void volatile while",
        "C#": "abstract as async await base bool break byte case catch char checked class const continue decimal default delegate do double else enum event explicit extern false finally fixed float for foreach goto if implicit in int interface internal is lock long namespace new null object operator out override params private protected public readonly ref return sbyte sealed short sizeof stackalloc static string struct switch this throw true try typeof uint ulong unchecked unsafe ushort using virtual void volatile while",
        "Java": "abstract assert boolean break byte case catch char class const continue default do double else enum extends final finally float for goto if implements import instanceof int interface long native new null package private protected public return short static strictfp super switch synchronized this throw throws transient true try void volatile while",
        "Go": "break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var",
        "Rust": "as async await break const continue crate dyn else enum extern false fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait true type unsafe use where while",
        "Shell": "case do done elif else esac fi for function if in select then time until while",
        "PowerShell": "begin break catch class continue data do dynamicparam else elseif end enum exit filter finally for foreach from function if in param process return switch throw trap try until using var while",
        "SQL": "add all alter and any as asc backup between by case check column constraint create database default delete desc distinct drop exec exists foreign from full group having in index inner insert into is join key left like limit not null on or order outer primary procedure right rownum select set table top truncate union unique update values view where",
    }

    def __init__(self, document, language: str):
        super().__init__(document)
        self.language = language
        self.rules = []
        self._build_rules()

    def _add(self, pattern: str, text_format: QTextCharFormat):
        self.rules.append((QRegularExpression(pattern), text_format))

    def _build_rules(self):
        keyword_format = _format("#c7b7d8", bold=True)
        string_format = _format("#b8c99c")
        number_format = _format("#d8c39a")
        comment_format = _format("#77736d", italic=True)
        function_format = _format("#8bc7a8")
        property_format = _format("#d7c6a5")
        tag_format = _format("#c7b7d8")

        keywords = self.COMMON_KEYWORDS.get(self.language, "")
        if keywords:
            escaped = "|".join(QRegularExpression.escape(word) for word in keywords.split())
            self._add(rf"\b(?:{escaped})\b", keyword_format)

        self._add(r"\b(?:0[xX][0-9A-Fa-f]+|\d+(?:\.\d+)?)\b", number_format)
        self._add(r'"(?:\\.|[^"\\])*"', string_format)
        self._add(r"'(?:\\.|[^'\\])*'", string_format)

        if self.language in {"Python", "Shell", "PowerShell", "YAML", "TOML", "INI", "Config", "Makefile", "Dockerfile"}:
            self._add(r"#[^\n]*", comment_format)
        elif self.language not in {"HTML", "XML", "Markdown"}:
            self._add(r"//[^\n]*", comment_format)

        if self.language in {"Python", "JavaScript", "TypeScript", "Go", "Rust"}:
            self._add(r"\b[A-Za-z_][A-Za-z0-9_]*(?=\s*\()", function_format)
        if self.language == "JSON":
            self._add(r'"(?:\\.|[^"\\])*"(?=\s*:)', property_format)
        if self.language in {"HTML", "XML"}:
            self._add(r"</?[A-Za-z][^>]*>", tag_format)
        if self.language == "Markdown":
            self._add(r"^#{1,6}\s+.*$", keyword_format)
            self._add(r"`[^`]+`", string_format)

    def highlightBlock(self, text: str):
        for expression, text_format in self.rules:
            matches = expression.globalMatch(text)
            while matches.hasNext():
                match = matches.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), text_format)
