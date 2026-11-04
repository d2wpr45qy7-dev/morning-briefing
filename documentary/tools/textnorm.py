import re
from difflib import SequenceMatcher

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_TENS_PL = ["", "", "twenties", "thirties", "forties", "fifties", "sixties", "seventies", "eighties", "nineties"]
ORDINALS = {"II": "the Second", "III": "the Third", "IV": "the Fourth", "V": "the Fifth", "VI": "the Sixth",
            "VII": "the Seventh", "VIII": "the Eighth", "IX": "the Ninth", "X": "the Tenth"}
_YEAR_CTX = r"(?:[Ii]n|[Bb]y|[Aa]round|[Ff]rom|[Uu]ntil|[Ss]ince|[Oo]f|year)"


def n2w(n):
    if n < 20:
        return _ONES[n]
    return _TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else "")


def year_words(y):
    if y in (1000, 2000):
        return "one thousand" if y == 1000 else "two thousand"
    if 2001 <= y <= 2009:
        return "two thousand " + n2w(y - 2000)
    hi, lo = divmod(y, 100)
    if lo == 0:
        return n2w(hi) + " hundred"
    if lo < 10:
        return f"{n2w(hi)} oh {n2w(lo)}"
    return f"{n2w(hi)} {n2w(lo)}"


def speakable(s):
    """Text as the narrator should say it: years as years, regnal numerals as ordinals, no stray symbols."""
    s = s.replace("—", ", ").replace('"', "")
    s = re.sub(r"\bSt\. ", "Saint ", s)
    s = re.sub(r"\b([A-Z][a-z]+) (II|III|IV|V|VI|VII|VIII|IX|X)\b", lambda m: f"{m.group(1)} {ORDINALS[m.group(2)]}", s)
    s = re.sub(r"\bAlexios I\b", "Alexios the First", s)
    s = re.sub(r"(?<![\d,])(\d{2})00s\b", lambda m: f"{n2w(int(m.group(1)))} hundreds", s)
    s = re.sub(r"(?<![\d,])(\d)(\d)0s\b", lambda m: f"{n2w(int(m.group(1)))} {_TENS_PL[int(m.group(2))]}", s)
    s = re.sub(r"(?<![\d,])(1\d{3}|20\d{2})\b(?![,.]?\d)", lambda m: year_words(int(m.group(1))), s)
    s = re.sub(rf"\b({_YEAR_CTX}) (\d)(\d{{2}})\b(?!\s*(?:-|years?\b))",
               lambda m: f"{m.group(1)} {_ONES[int(m.group(2))]} " + (
                   "hundred" if m.group(3) == "00" else f"oh {n2w(int(m.group(3)))}" if m.group(3)[0] == "0"
                   else n2w(int(m.group(3)))), s)
    s = re.sub(r"(?<=\d),(?=\d{3}\b)", "", s)
    return s


def norm(w):
    return re.sub(r"[^a-z0-9]", "", w.lower())


def align_words(words, heard):
    """Match script words to Whisper words ({'w','s','e'}); unmatched stretches spread evenly over the audio they span."""
    a, b = [norm(w) for w in words], [norm(h["w"]) for h in heard]
    times = [None] * len(words)
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                times[i1 + k] = (heard[j1 + k]["s"], heard[j1 + k]["e"])
        elif i2 > i1:
            if j2 > j1:
                s0, e0 = heard[j1]["s"], heard[j2 - 1]["e"]
            else:
                s0 = heard[j1 - 1]["e"] if j1 > 0 else 0.0
                e0 = max(heard[j1]["s"] if j1 < len(heard) else heard[-1]["e"], s0 + 0.05 * (i2 - i1))
            step = (e0 - s0) / (i2 - i1)
            for k in range(i2 - i1):
                times[i1 + k] = (s0 + k * step, s0 + (k + 1) * step)
    return times


def parse_script(path):
    """Return [(section_title or None, paragraph_text)] in order; headings start with '## '."""
    out, section = [], None
    for b in (x.strip() for x in open(path, encoding="utf-8").read().split("\n\n")):
        if not b or b.startswith("# ") or b == "---":
            continue
        if b.startswith("## "):
            section = b[3:].strip()
            continue
        out.append((section, b))
        section = None
    return out
