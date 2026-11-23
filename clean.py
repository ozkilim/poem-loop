"""Output cleaning: strip <think> blocks, chatty lead-ins, and trailing notes."""
import re

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S | re.I)
_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*\n(.*?)\n\s*```\s*$", re.S)
_SEP = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,}|={3,})\s*$")

# A first line that is the model talking, not the poem.
_LEADIN = re.compile(
    r"^\s*(\*\*)?\s*("
    r"here('s| is| are)\b|"
    r"sure\b|certainly\b|of course\b|absolutely\b|okay\b|ok\b|great\b|"
    r"i('ve| have)\s+(re)?(written|revised|crafted|reworked|rewritten)|"
    r"(below|this) is\b|"
    r"(the\s+)?revised (version|poem)\b|"
    r"rewritten (version|poem)\b"
    r").*$",
    re.I,
)

# Trailing-note detection. A "strong" opener is unambiguous ("Note:", "**Changes made**").
# A "weak" opener ("I have...", "This version...") only counts if the paragraph talks about the poem itself.
_NOTE_STRONG = re.compile(
    r"^\s*[\*_\(\[#>]*\s*(notes?|changes?( made)?|explanation|revisions?( made)?|what (i )?changed|"
    r"key (changes|revisions|improvements)|why (this|it) works|author'?s note)\b[^\n]{0,40}?[:\*_\)\]]",
    re.I,
)
_NOTE_WEAK = re.compile(
    r"^\s*[\*_\(\[]*\s*(i('ve| have)?\s+(made|kept|changed|tried|removed|added|focused|aimed|revised|rewritten|"
    r"reworked|tightened|replaced|cut|leaned|incorporated)\b|this (version|revision|rewrite|revised)\b|"
    r"in this (version|revision|rewrite)\b|the (revised|new) (version|poem)\b|(the )?feedback\b|"
    r"let me know\b|i hope\b)",
    re.I,
)
_META = re.compile(r"\b(feedback|revis\w*|version|rewrite|rewritten|stanzas?|imagery|meter|metre|rhyme scheme|"
                   r"clich\w*|the poem|this poem|line \d+)\b", re.I)


def _is_leadin(line: str) -> bool:
    """Chatty opener, not a first line of verse: must also mention the poem/rewrite, end with ':',
    or be a bare interjection like 'Sure!'."""
    if len(line) > 200 or not _LEADIN.match(line):
        return False
    l = line.strip().strip("*_ ")
    return bool(_META.search(l) or l.endswith(":") or
                re.match(r"(?i)(sure|certainly|of course|absolutely|okay|ok|great)\s*[!,.]", l))


def strip_think(text: str) -> str:
    if text is None:
        return ""
    text = _THINK_BLOCK.sub("", text)
    # Unclosed / orphan tags: drop everything up to a stray </think>, and any trailing open <think>.
    if re.search(r"</think>", text, re.I):
        text = re.split(r"</think>", text, flags=re.I)[-1]
    # An unclosed <think> means everything after it is thinking (truncated); drop it.
    text = re.split(r"<think>", text, flags=re.I)[0]
    text = text.replace("/no_think", "")
    return text.strip()


def clean_feedback(text: str) -> str:
    return strip_think(text).strip()


def clean_poem(text: str) -> str:
    t = strip_think(text)
    m = _FENCE.match(t)
    if m:
        t = m.group(1)
    lines = t.strip("\n").split("\n")

    # Lead-ins: drop leading chatty lines (and a separator right after them).
    while lines and (not lines[0].strip() or _is_leadin(lines[0])):
        lines.pop(0)
        while lines and (not lines[0].strip() or _SEP.match(lines[0])):
            lines.pop(0)

    # Trailing notes: cut at the first paragraph (after a blank line or separator) that is the model
    # explaining itself. Everything from there on is dropped.
    n = len(lines)
    for i in range(1, n):
        if lines[i - 1].strip() and not _SEP.match(lines[i - 1]):
            continue  # notes start a new paragraph
        prev_sep = any(_SEP.match(lines[j]) for j in range(max(0, i - 2), i))
        para = []
        for l in lines[i:]:
            if not l.strip():
                break
            para.append(l)
        para_txt = " ".join(para)
        strong = bool(_NOTE_STRONG.match(lines[i]))
        weak = bool(_NOTE_WEAK.match(lines[i])) and bool(_META.search(para_txt))
        if strong or weak or (prev_sep and i >= n * 0.5 and _META.search(para_txt) and len(para_txt) > 60):
            lines = lines[:i]
            break

    # Drop trailing separators / blank lines left behind; also lone code fences.
    while lines and (not lines[-1].strip() or _SEP.match(lines[-1]) or lines[-1].strip().startswith("```")):
        lines.pop()
    while lines and lines[0].strip().startswith("```"):
        lines.pop(0)
    return "\n".join(l.rstrip() for l in lines).strip()
