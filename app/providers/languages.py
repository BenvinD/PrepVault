# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Unified programming-language naming across judges.

Different judges report languages in different shapes — HackerRank uses slugs
like ``cpp`` / ``python3`` / ``java8``, LeetCode uses ``langName`` values like
``C++`` / ``Python3``, manual entries are free text. ``normalize_language``
maps all of them to a single canonical label so the UI, stats and language
filters stay consistent regardless of source.
"""

from __future__ import annotations

import re

# Canonical labels keyed by a normalized (lowercased, de-versioned) token.
_CANONICAL: dict[str, str] = {
    "c": "C",
    "c++": "C++", "cpp": "C++", "g++": "C++", "gpp": "C++", "clang++": "C++",
    "objective-c": "Objective-C", "objectivec": "Objective-C", "objc": "Objective-C",
    "c#": "C#", "csharp": "C#", "cs": "C#",
    "java": "Java",
    "kotlin": "Kotlin", "kt": "Kotlin",
    "scala": "Scala",
    "groovy": "Groovy",
    "python": "Python", "py": "Python", "pypy": "Python", "cpython": "Python",
    "javascript": "JavaScript", "js": "JavaScript", "node": "JavaScript", "nodejs": "JavaScript",
    "typescript": "TypeScript", "ts": "TypeScript",
    "go": "Go", "golang": "Go",
    "ruby": "Ruby", "rb": "Ruby",
    "rust": "Rust", "rs": "Rust",
    "swift": "Swift",
    "php": "PHP",
    "perl": "Perl",
    "bash": "Bash", "shell": "Bash", "sh": "Bash", "zsh": "Bash",
    "haskell": "Haskell", "hs": "Haskell",
    "lua": "Lua",
    "r": "R", "rlang": "R",
    "dart": "Dart",
    "elixir": "Elixir", "ex": "Elixir",
    "erlang": "Erlang", "erl": "Erlang",
    "clojure": "Clojure", "clj": "Clojure",
    "ocaml": "OCaml",
    "fsharp": "F#", "f#": "F#",
    "racket": "Racket",
    "scheme": "Scheme",
    "lisp": "Lisp", "commonlisp": "Lisp", "sbcl": "Lisp", "clisp": "Lisp",
    "julia": "Julia",
    "pascal": "Pascal",
    "fortran": "Fortran",
    "cobol": "COBOL",
    "ada": "Ada",
    "d": "D",
    "tcl": "Tcl",
    "visualbasic": "Visual Basic", "vb": "Visual Basic", "vbnet": "Visual Basic",
    "smalltalk": "Smalltalk",
    "pandas": "Pandas",
    # SQL flavours unify to SQL.
    "sql": "SQL", "mysql": "SQL", "oracle": "SQL", "tsql": "SQL", "mssql": "SQL",
    "ms sql server": "SQL", "postgresql": "SQL", "postgres": "SQL", "db2": "SQL", "plsql": "SQL",
}

# Trailing version tokens to strip, e.g. cpp14 -> cpp, java8 -> java, python3 -> python.
_VERSION_RE = re.compile(r"[\s_\-]?\d+$")


def normalize_language(raw: str | None) -> str | None:
    """Return a canonical language label for any judge/manual value."""
    if not raw:
        return None
    key = raw.strip().lower()
    if not key:
        return None
    if key in _CANONICAL:
        return _CANONICAL[key]
    base = _VERSION_RE.sub("", key)
    if base in _CANONICAL:
        return _CANONICAL[base]
    # Collapse separators (e.g. "ms-sql") before a final lookup.
    collapsed = base.replace("-", "").replace("_", "").replace(" ", "")
    if collapsed in _CANONICAL:
        return _CANONICAL[collapsed]
    # Unknown — return the original trimmed value so nothing is lost.
    return raw.strip()


def normalize_languages(values) -> list[str]:
    """Normalize an iterable of language values, de-duplicated, order-preserving."""
    out: list[str] = []
    for v in values:
        n = normalize_language(v)
        if n and n not in out:
            out.append(n)
    return out
