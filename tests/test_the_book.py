"""THE BOOK OF SAURON (2026-09-27): /book/, the public story beside the Wall.

The operator asked for a "Sauron Bible / book" page in the public part of
the site: the story, what the platform is, the current work; then "bring
lots of animations and good designs please".

What this file pins:

  * the page answers 200 to anyone, speaks the Wall's design (its colours,
    its fonts, its icons, nothing else external), links to the Wall and is
    linked from it, and renders every chapter, era, milestone and word;
  * every count it prints comes from core.wall_facts (patched here: the
    page follows), no number is typed into the template, and every other
    figure on the page is a dated fact listed below with its source;
  * PUBLIC SAFETY, over every byte of the answer (its text, its <head>, its
    <style> and <script> blocks, their comments): none of the private
    terms, no account figure, identifier, host, command or key, no e-mail,
    no IP, no commit hash; the staff-only chapter is not in the answer at
    all, for an anonymous reader or a plain signed-in user, and the file it
    lives in is never even opened for them; staff receives it word for
    word, never cached. The private terms are stored as digests, and the
    staff-only chapter is not in this repository at all (a neutral fixture
    stands in for it here): the repository is public;
  * clean English: no snake_case, no template artefact, no French;
  * the road so far is held to the history as it stood at 3994ffc (the
    container has no .git to ask): every hash exists, every milestone is
    dated on its commit's day or up to three days before it;
  * motion is optional: nothing is hidden unless the head script says
    motion is welcome, prefers-reduced-motion and print stop everything and
    show everything, the keyframes move only transform and opacity, no
    animation runs on a shape inside an <svg>, and the numbers are printed
    at their counted value before any script runs;
  * phone first, dark like the Wall; the route is in the probe's walk.
"""
import datetime
import hashlib
import html
import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core import book_content as book
from core import views_book
from core import wall_facts as wf

BOOK = "/book/"
REPO = Path(settings.BASE_DIR)
TEMPLATE = REPO / "templates" / "landing" / "the_book.html"

#: The history at 3994ffc, as `git log --pretty='%h %ad' --date=short`
#: printed it on 2026-09-27: every commit's short hash and day.
HISTORY_AT_3994FFC = """
3994ffc 2026-09-28
c3d12e9 2026-09-27
a92454a 2026-09-27
cf30b5d 2026-09-27
8db05d5 2026-09-27
0a9133a 2026-09-27
92d1c11 2026-09-27
ab47af2 2026-09-27
097e72c 2026-09-27
2882a94 2026-09-27
9df34a7 2026-09-27
daf1343 2026-09-26
48689f7 2026-09-26
0da2faa 2026-09-26
1f36b2d 2026-09-26
fae29b4 2026-09-26
37836e1 2026-09-26
7759c43 2026-09-25
caf0811 2026-09-24
526aa82 2026-09-24
c5375f5 2026-09-24
0f9909c 2026-09-24
adcfdbd 2026-09-23
aa5cfb2 2026-09-23
c5b41df 2026-09-23
8499041 2026-09-23
9b8d958 2026-09-23
db09002 2026-09-23
976e06d 2026-09-23
3ac446f 2026-09-23
20fa370 2026-09-23
8eddee1 2026-09-23
b00df4d 2026-09-23
352f154 2026-09-23
21c0fd7 2026-09-23
ea0bb54 2026-09-23
5078365 2026-09-22
9eb827f 2026-09-22
4440bd6 2026-09-22
f4fdb91 2026-09-20
2431d96 2026-09-20
aa53b4d 2026-09-20
94a79f2 2026-09-20
0e4fa38 2026-09-20
d3c735f 2026-09-20
662937a 2026-09-20
31db6e7 2026-09-20
a72b756 2026-09-20
1da56db 2026-09-20
7b92b62 2026-09-19
7aaf06d 2026-09-18
14d7907 2026-09-17
eaa68da 2026-09-17
2f0e585 2026-09-17
dc08cdf 2026-09-17
a799e8e 2026-09-17
ac56303 2026-09-17
02bbefb 2026-09-15
a35e404 2026-09-15
530e18d 2026-09-15
dcfbe92 2026-09-15
43af37f 2026-09-14
6ee5eb7 2026-09-14
d1d0957 2026-09-14
d063c3f 2026-09-13
65055ec 2026-09-13
4e2ec0f 2026-09-13
a5d18e7 2026-09-13
5a76df9 2026-09-13
e16f29e 2026-09-13
cac1091 2026-09-13
b0a33dd 2026-09-13
e3ee60f 2026-09-13
8668662 2026-09-13
bfe4625 2026-09-13
a48feb0 2026-09-13
0cfda6b 2026-09-13
727a403 2026-09-13
9a0590b 2026-09-13
266f57b 2026-09-12
3d71d3b 2026-09-12
56bf344 2026-09-12
83b3fa0 2026-09-12
2d063ed 2026-09-12
464633f 2026-09-12
c3ff48a 2026-09-12
0550e39 2026-09-12
bcc5262 2026-09-12
fae5b83 2026-09-12
475b584 2026-09-12
e34cb76 2026-09-12
5826b03 2026-09-12
3af0a2c 2026-09-12
7567626 2026-09-12
4d84a58 2026-09-12
c2cdbb0 2026-09-12
1a3c802 2026-09-12
c6b3f46 2026-09-12
3e23fd9 2026-09-11
c17dcc4 2026-09-11
6178e3a 2026-09-11
b1ce25f 2026-09-11
c8c2e79 2026-09-11
a920d8d 2026-09-11
113b3ed 2026-09-11
b357f51 2026-09-11
daf3874 2026-09-10
bd4f40e 2026-09-10
14ceff3 2026-09-10
1901da1 2026-09-10
48edfcc 2026-09-10
10863a8 2026-09-10
9eba260 2026-09-08
86dd531 2026-09-07
5f5ac1b 2026-09-07
3f9681b 2026-09-07
6b972ea 2026-09-07
b781598 2026-09-07
45436ec 2026-09-07
7fb3c5f 2026-09-07
3767b89 2026-09-06
9e2bc10 2026-09-06
eac2c01 2026-09-01
0b6d44a 2026-09-01
d0627ee 2026-09-01
5ba1af8 2026-08-31
78b6c27 2026-08-31
039891b 2026-08-31
a2e0e10 2026-08-31
b46f104 2026-08-31
6728aa0 2026-08-31
3189bf5 2026-08-30
5b0bbe6 2026-08-30
4fadfb7 2026-08-30
106f1e2 2026-08-30
4fff77c 2026-08-30
4b9e45d 2026-08-30
1bd286e 2026-08-30
3838bf2 2026-08-30
44be164 2026-08-29
289fbc4 2026-08-29
4b0a43e 2026-08-29
1dfd195 2026-08-29
021e66e 2026-08-29
5c864bc 2026-08-28
210ec0e 2026-08-28
f9a835a 2026-08-28
d9a30b2 2026-08-28
0896e2c 2026-08-28
21da034 2026-08-28
d6d7242 2026-08-28
d91facc 2026-08-27
3fefb52 2026-08-27
8bc6fce 2026-08-27
af0b5bc 2026-08-27
4b4169d 2026-08-27
e0f3959 2026-08-27
b9292c7 2026-08-27
a6e271b 2026-08-27
ea4c91e 2026-08-27
6a9037f 2026-08-27
ce6e1cd 2026-08-27
8411e9a 2026-08-26
9b44356 2026-08-26
eb22386 2026-08-26
e35fca4 2026-08-25
3120fb6 2026-08-25
d32e8b9 2026-08-25
35b3fc9 2026-08-25
a0115e8 2026-08-25
10406e8 2026-08-25
430cad7 2026-08-25
734a246 2026-08-25
48d814d 2026-08-25
586f4a4 2026-08-25
b8db750 2026-08-25
692ae12 2026-08-25
a12325a 2026-08-25
3f483d8 2026-08-24
ce21b44 2026-08-24
bfc3af5 2026-08-24
a3aab77 2026-08-24
d86cbcf 2026-08-24
bb013a1 2026-08-21
2863988 2026-08-21
8c54a59 2026-08-21
03f90e5 2026-08-21
8dfac5f 2026-08-20
318d857 2026-08-20
f35e9d0 2026-08-20
a12722c 2026-08-19
c13708c 2026-08-19
3855bb2 2026-08-19
e9b0dd3 2026-08-19
51bf538 2026-08-19
29bb1d3 2026-08-19
feb2b10 2026-08-19
0342715 2026-08-19
b4e389f 2026-08-19
8264035 2026-08-19
449816d 2026-08-18
7611cb2 2026-08-18
249b5e8 2026-08-18
2aead85 2026-08-18
764e323 2026-08-18
3cbe3a0 2026-08-18
b1b9995 2026-08-18
3ae7e1a 2026-08-18
4b4dcb9 2026-08-18
7c3c812 2026-08-18
d84d1db 2026-08-17
96d8616 2026-08-17
e33fd7d 2026-08-17
c46e863 2026-08-17
da9680d 2026-08-16
0ec7ef5 2026-08-16
fe16f72 2026-08-15
2fe6a15 2026-08-15
392823d 2026-08-15
1dca844 2026-08-15
a2cd665 2026-08-15
f40c49f 2026-08-14
8b72d94 2026-08-14
c4deca3 2026-08-14
d77a213 2026-08-14
e75a9cd 2026-08-14
d80121d 2026-08-14
a8653ce 2026-08-13
c41e603 2026-08-10
a96de99 2026-08-10
ba3ba5a 2026-08-10
e91eb62 2026-08-10
ff0abae 2026-08-10
6bf2f06 2026-08-09
fab371e 2026-08-09
38c6cf5 2026-08-09
0d8dbdc 2026-08-09
a199573 2026-08-09
458a754 2026-08-09
91caad4 2026-08-09
2d69c09 2026-08-09
c2c0ca4 2026-08-09
0883842 2026-08-09
920158f 2026-08-09
315eab0 2026-08-09
feb233a 2026-08-09
f29d792 2026-08-09
46460e9 2026-08-09
c36b49c 2026-08-09
ab8ccaf 2026-08-09
e7ff73b 2026-08-09
8de338e 2026-08-09
da85002 2026-08-09
f9a7108 2026-08-09
7a9be31 2026-08-09
a2d5080 2026-08-09
59a4bf0 2026-08-09
acaa3de 2026-08-09
a0081c5 2026-08-09
ddfa08c 2026-04-11
bd2aef1 2026-04-11
f64b3b1 2026-04-11
a23f7cb 2026-04-11
712abc6 2026-04-11
8bd7fcb 2026-04-11
dfdc332 2026-04-11
89d7c83 2026-04-11
d5094f0 2026-04-10
5e4a612 2026-04-10
4dcd8be 2026-04-10
f7114f4 2026-04-10
4555011 2026-04-10
9791733 2026-04-10
f8a5367 2026-04-10
7fc993a 2026-04-09
3c74677 2026-04-09
848af6e 2026-04-09
8701a6e 2026-04-09
a23e130 2026-04-09
b02cc43 2026-04-09
0ef3fda 2026-04-09
2a2bb50 2026-04-09
b2e9a60 2026-04-09
a10b2c9 2026-04-09
893d348 2026-04-09
ddd9967 2026-04-09
b0edff8 2026-04-09
42ac69e 2026-04-09
4626ce8 2026-04-09
5169ed3 2026-04-09
b1086e6 2026-04-08
e96f74c 2026-04-08
2e161c5 2026-04-08
b5cec3b 2026-04-08
b3f3e0b 2026-04-08
bb7cbce 2026-04-07
07c9402 2026-04-06
b5c831a 2026-04-06
96d84a4 2026-04-06
d7d9f9a 2026-04-06
b28eb2c 2026-04-06
de640cd 2026-04-06
0214e9a 2026-04-06
54e35ba 2026-04-05
"""
KNOWN_COMMITS = dict(line.split() for line in HISTORY_AT_3994FFC.split("\n")
                     if line.strip())

#: Generic words and phrases the public page must never carry, anywhere in
#: the answer (compared lowercased, entities decoded). The private ones are
#: PRIVATE_TERM_DIGESTS below.
FORBIDDEN_WORDS = [
    # the account
    "balance", "equity", "p&l", "pnl", "profit and loss",
    "account number", "account id", "order id", "orderid", "position id",
    "positionid", "usd", "€", "$",
    # identifiers, keys, hosts, commands
    "chat id", "chat_id", "api key", "api_key", "user key", "user_key",
    "secret", "token", "password", "vps", "ssh ", "docker", "compose",
    "caddy", "daphne", "gunicorn", "celery", "redis", "postgres", "nginx",
    "hostname", "localhost", "127.0.0.1", "manage.py", ".env", "sudo",
    "systemctl", "git pull", "--yes", "/stop", "/status",
]
#: The stylesheet's own words that share letters with the list above.
CODE_WORDS = ("text-wrap: balance",)

#: The private terms (identity, whereabouts, who holds what, the e-mail,
#: the instruments held), each as the sha256 of its lowercased words joined
#: by one space. This repository is public: a list of what must stay
#: private, typed in clear, would say it. One digest is a canary, CANARY,
#: which the tests plant to prove the walk finds a term wherever it hides.
PRIVATE_TERM_DIGESTS = frozenset({
    "01fa2c6f247019ae32c4c7ab4e6c228c172d4e755cdbe49e4c6a28f604411fd9",
    "033e8cf207eb4128b6a4f96a93635b78a0d3ef28bfa5136c765e811241956349",
    "058e976492d47aab16c98232d93c17e00deced02a92a265f0f6430377f9694a0",
    "070969f9c60b2378686b68e2c9d1713159b4ec871eb880d563c4b460d4fe5498",
    "13f393891c57b11a085ba660c6a11e41e60c03c65d079f1e22606b1ee00484f5",
    "1614ceeec50a9336ebf690886caa747d6811c45d37086a3fa7b11c9e83926c6c",
    "1888101dae1d8fc2c5644effea1127664fa6f5244ec651cf4dfc212d5a1cb540",
    "199dc38e1a4d3008afbe8de87653c31bd4143a501f47539022b8340ebdfecc30",
    "19acb093f04ad04bdaff2c981d1a4f53c0978782af949b3017a1955cc77f5abc",
    "1fed856c13a209f0ab71a7ed89c13d9f74385689fd0f3c84091fbacd27f6e476",
    "2123abbaac7753cab5f7bf55dd765c16306c38aa5138f841029848bef4a5f207",
    "2502770bb9c2bc900120093d00e8bc5ca4eecf4f6e348f9edf2eb879e2e9c1d0",
    "2ef8109cfc2c927f8e416368293c3f488b44748e7f6090f9e911f276e807a1a6",
    "378ce56a9d146d5174c89d1c0353d7f8e2244e89bb83935a5b1bdcf5e74b4e7f",
    "45d4b5a2b736dd16e8ba2283aa3b642e665ba460f8610fb4c1e5746607a0fd64",
    "485ef000344c201d24d44df3cf542f3b490a9fd553f03e396fe2fbd69d2324ee",
    "50497e484ebb22c3b1c3ec1cb2d86d623be14c5bfa9f119526afc463ce2fcb2b",
    "576ba7c2e4abb7184ca409154dbbbd5306c1a80747fbce4148ea6271fd21e776",
    "58cc6181518fbfb49da9c50db08ce31aa92feebaecc6c46a3a8084e87b50f037",
    "5ad38304b535c2987dbd24657c1a11b884984ff600d9f389deb0d4e634fee792",
    "72b528f9c86487399dfdf6694732395e191628b5fecb73d3bfec59ee856e65d8",
    "81e058fbc7c1d5c79a3ebe55f8305211d689d31e6092ccce9d789dac35f894cd",
    "84d1d10378db821681de841abc0828e4ac4d3f593da3cbaea3f66c5af251cc88",
    "88a1881f0025cf7117501d07aefc5d4be6696656790d765678df8bc48ca52687",
    "8f60e4c409b48faf48d4bccdc82e4cb2b31cdf9f130e52b73695f0d954de908e",
    "929d4b9ed70f57653b154b48e229fd7615f095b4fb9b886eb9db1a8c3987d1f4",
    "99626eb121d1e6b56bd715fbe0710127ace02a9b3ba397246f64fb2f0748a15c",
    "9a14f3160283d6ac09436b7c954ba9708f3a07d1ee130f19776bc4f3def4bf1b",
    "9a7db5a31b7019d0e0714c54614ded70cdb0d15e2e96a1ed6ec43b89595fa7af",
    "ba45de9343234cbec3676f988262f152c8815e297ffdb2adeb6ec7a5d22e4f03",
    "bd7e190fce14ea4737d707e678b608bc5570125883c54ed63f8a874d16854665",
    "cc2e94bebec101520d06503709c01148181f6446b9b078dd861a2dbb87237ebe",
    "d7b44e006ff0b71a5aed38e4794bbcdb4e4eb7ffae8983ec9818bd3e596b93d7",
    "e27d22eee452aea8bc8babb98c5830f453783ad089a5e2ac466bb2019345c516",
    "e287b6aacc447c8468fd53380c62d8a7072fcd79bf5364f0f4c26d629ad83551",
    "e40605e6a26268a5eb83c155ea5dd12aeb3314f6ba5d67d4b607de95156e4e12",
    "f1522aa90652155c67df431da6f23af0d8897a677cfdd24377ad78214d3241dc",
    "f2f457bb12d5f918db2d33ecaa409376887189728c6bd1c4c5bd584904db7fda",
})
PRIVATE_TERM_MAX_WORDS = 4
CANARY = "canary private phrase"

#: Searched over the whole answer, and over its visible text.
WHOLE_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "an e-mail address"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"), "an IP address"),
    (re.compile(r"(?<![\d,.])\d{5,}(?![\d,])"), "an identifier-length digit run"),
]
VISIBLE_PATTERNS = [
    (re.compile(r"\bpositions?\b"), "a position"),
    # the brake's command ("bot off 12"), not the English "switch a bot off"
    (re.compile(r"\bbot off \d"), "a command"),
]

#: Every figure the page may print that is not a wall_facts count or part
#: of a date or a time: each is a dated fact of the history or a default
#: the circuit chapter dates ("as verified on 26 September 2026").
DATED_FIGURES = {
    "304": "commits when this book was written (the stored history)",
    "45": "commits in April 2026",
    "134": "commits in August 2026",
    "125": "commits in September 2026, up to 3994ffc",
    "259": "commits co-written with Claude, every one since 9 August",
    "166": "symbols the research fleet covered, 11-15 September",
    "667": "the tests the Wall once claimed, before wall_facts",
    "7,459": "the tests that held the eToro layers right on 22 September",
    "24": "hours: the oldest signal the vote reads (default, 26 September)",
    "0.60": "the lowest signal score that votes (default)",
    "1.5": "the stop in average moves (default)",
    "3": "the target in average moves (default)",
    "0.25": "per cent of the bot's reserve risked per trade (default)",
    "5": "per cent: how far from the price a stop was sent on 26 September (ab47af2)",
    "10": "per cent, nearly: how far eToro held that stop (ab47af2)",
    "15": "minutes between two comparisons with the broker (default)",
    "0": "what the public pages show for a failed counter, deliberately",
    "1": "1R and -1R, the unit of risk",
    "2": "+2R, twice the risk",
}

MONTHS = ("January|February|March|April|May|June|July|August|September|"
          "October|November|December")
DATE_RE = re.compile(
    r"\b\d{1,2}(?:\s*–\s*\d{1,2})?\s+(?:%s)(?:\s+\d{4})?" % MONTHS, re.I)
DAY_RE = re.compile(r"\bthe \d{1,2}(?:st|nd|rd|th)\b")
TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")
NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*")

#: A neutral stand-in for the staff-only chapter (the real one is private
#: and lives outside git; only its sha256 is in core/views_book.py).
FIXTURE = {
    "label": "Staff reading",
    "note": "written for the tests",
    "lang": "fr",
    "chapter": {
        "id": "fixture",
        "title": "Un chapitre d'essai",
        "kicker": "Écrit pour les tests, et pour personne d'autre.",
        "paragraphs": [
            "Premier paragraphe du chapitre d'essai.",
            "Second paragraphe, avec une apostrophe : l'essai tient.",
        ],
        "items": [
            {"label": "Une étiquette", "text": "Un texte d'essai « entre guillemets »."},
            {"label": "Une autre", "text": "Un second texte d'essai."},
        ],
    },
}


def _fixture_words():
    chapter = FIXTURE["chapter"]
    return ([FIXTURE["label"], FIXTURE["note"], chapter["title"], chapter["kicker"]]
            + chapter["paragraphs"]
            + [item["label"] for item in chapter["items"]]
            + [item["text"] for item in chapter["items"]])


def _tokens(text):
    return re.findall(r"[^\W_]+", unicodedata.normalize("NFC", text).lower())


def _private_terms_in(text):
    """Every private term the text carries, as the text itself says it."""
    words = _tokens(text)
    found = set()
    for n in range(1, PRIVATE_TERM_MAX_WORDS + 1):
        for i in range(len(words) - n + 1):
            gram = " ".join(words[i:i + n])
            if hashlib.sha256(gram.encode("utf-8")).hexdigest() in PRIVATE_TERM_DIGESTS:
                found.add(gram)
    return sorted(found)


def _whole(body):
    """Every byte a visitor receives, entities decoded, lowercased: the
    <head>, the <style> and <script> blocks and every comment included.
    The counted numbers' own attribute is taken out (a large count is not
    an identifier), and so are the colours (#030806 is the page's black)
    and the stylesheet's own words (CODE_WORDS)."""
    text = re.sub(r'data-count="\d+"', " ", html.unescape(body)).lower()
    text = re.sub(r"#[0-9a-f]{3,8}(?![0-9a-z])", " ", text)
    for word in CODE_WORDS:
        text = text.replace(word, " ")
    return text


def _visible(body):
    """The words a visitor reads."""
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.S)
    body = re.sub(r"<(style|script|head)\b.*?</\1>", " ", body,
                  flags=re.S | re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", body))
    return " ".join(text.split())


def _leaks(body):
    """What an answer carries that a public page must not, in words."""
    whole = _whole(body)
    found = ["says %r" % word for word in FORBIDDEN_WORDS if word in whole]
    found += ["carries the private term %r" % gram for gram in _private_terms_in(whole)]
    for pattern, what in WHOLE_PATTERNS:
        hit = pattern.search(whole)
        if hit:
            found.append("shows %s: %r" % (what, hit.group(0)))
    for _day, _era, _title, _words, commit in book.MILESTONES:
        if re.search(r"(?<![0-9a-f])%s(?![0-9a-f])" % commit, whole):
            found.append("shows the commit %s" % commit)
    visible = _visible(body)
    for pattern, what in VISIBLE_PATTERNS:
        hit = pattern.search(visible)
        if hit:
            found.append("shows %s: %r" % (what, hit.group(0)))
    if "@" in visible:
        found.append("shows an @")
    return found


def _css(body):
    return re.sub(r"/\*.*?\*/", "", re.search(
        r"<style>(.*?)</style>", body, re.S).group(1), flags=re.S)


def _drop_blocks(css, opener):
    """Remove every block that starts at `opener` (a regex), braces matched."""
    while True:
        m = re.search(opener, css)
        if not m:
            return css
        start = css.index("{", m.end() - 1)
        depth, i = 0, start
        while True:
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        css = css[:m.start()] + css[i + 1:]


def _block(css, opener):
    m = re.search(opener, css)
    start = css.index("{", m.end() - 1)
    depth, i = 0, start
    while True:
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return css[start + 1:i]
        i += 1


def _rules(css):
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        yield m.group(1).strip(), m.group(2).strip()


def _sentinels():
    """Every wall_facts key, each with its own unmistakable value."""
    return {key: 700001 + i for i, key in enumerate(wf.FALLBACK_FACTS)}


def _clear():
    cache.delete(wf.CACHE_KEY)


class _StaffChapterOnDisk:
    """The view pointed at a staff-only chapter file written here."""

    def put_chapter(self, data=FIXTURE, raw=None, pin=True):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "chapter.json"
        path.write_text(raw if raw is not None else json.dumps(data, ensure_ascii=False),
                        encoding="utf-8")
        env = mock.patch.dict(os.environ, {views_book.STAFF_CHAPTER_ENV: str(path)})
        env.start()
        self.addCleanup(env.stop)
        if pin:
            digest = mock.patch("core.views_book.STAFF_CHAPTER_SHA256",
                                views_book.chapter_digest(data["chapter"]))
            digest.start()
            self.addCleanup(digest.stop)
        return path


class TheBookServes(TestCase):

    def setUp(self):
        _clear()
        self.response = self.client.get(BOOK)
        self.body = self.response.content.decode("utf-8")

    def test_it_answers_anyone_with_its_template(self):
        self.assertEqual(self.response.status_code, 200)
        self.assertEqual(reverse("the_book"), BOOK)
        self.assertIn("landing/the_book.html",
                      [t.name for t in self.response.templates])

    def test_a_signed_in_reader_is_not_sent_elsewhere(self):
        """The Wall sends a signed-in user to the dashboard; the book does
        not: it is worth reading from inside too."""
        self.client.force_login(User.objects.create_user("book_plain", password="x"))
        response = self.client.get(BOOK)
        self.assertEqual(response.status_code, 200)

    def test_the_page_pays_none_of_a_dashboards_reads(self):
        """Rendered without the context processors: a signed-in reader's
        story page runs none of the dashboard's panels."""
        self.client.force_login(User.objects.create_user("book_reads", password="x", is_staff=True))
        response = self.client.get(BOOK)
        self.assertIn("book", response.context)
        for name in ("perms", "messages", "csrf_token"):
            self.assertNotIn(name, response.context)

    def test_it_speaks_the_walls_design(self):
        wall = self.client.get("/wall/").content.decode("utf-8")
        root = re.search(r":root\s*\{(.*?)\}", _css(wall), re.S).group(1)
        tokens = re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", root)
        self.assertGreater(len(tokens), 15)
        css = _css(self.body)
        for name, value in tokens:
            self.assertRegex(css, re.escape(name) + r"\s*:\s*" + re.escape(value.strip()) + ";",
                             "the book does not carry the Wall's %s" % name)
        fonts = re.search(r'<link href="(https://fonts\.googleapis\.com/[^"]+)"', wall).group(1)
        self.assertIn(fonts, self.body)
        for icon in ("logo/favicon.ico", "logo/sauron_eye.svg", "logo/favicon-32.png",
                     "logo/apple-touch-icon.png", "logo/og-card.png"):
            self.assertIn(icon, self.body)
        self.assertIn("color-scheme: dark", css)

    def test_nothing_external_but_the_walls_fonts(self):
        src = TEMPLATE.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"')]+", src):
            self.assertTrue(url.startswith(("https://fonts.googleapis.com", "http://www.w3.org/2000/svg")),
                            "the book reaches off the platform: " + url)
        self.assertNotIn("<script src", src)

    def test_it_links_to_the_wall_and_the_wall_links_back(self):
        self.assertIn('href="/wall/"', self.body)
        wall = self.client.get("/wall/").content.decode("utf-8")
        self.assertEqual(wall.count('href="/book/"'), 1)
        footer = wall[wall.index('<footer class="wall-footer">'):]
        self.assertIn('href="/book/"', footer[:footer.index("</footer>")])

    def test_every_chapter_is_rendered_whole(self):
        text = _visible(self.body)
        for chapter in book.CHAPTERS:
            self.assertIn('id="%s"' % chapter["id"], self.body)
            for words in [chapter["title"], chapter["kicker"], chapter["nav"]] + [
                    p for p in chapter["paragraphs"] if "{" not in p]:
                self.assertIn(words, text)
            for item in chapter.get("items", []):
                for key in ("title", "text"):
                    if key in item and "{" not in item[key]:
                        self.assertIn(item[key], text)
            for words in chapter.get("after", []) + [chapter.get("note", ""), chapter.get("loop", "")]:
                self.assertIn(words, text)
        for era in book.ERAS:
            self.assertIn(era["title"], text)
            self.assertIn(era["summary"], text)
        for day, _era, title, words, _commit in book.MILESTONES:
            self.assertIn(title, text)
            self.assertIn(words, text)
            self.assertIn('datetime="%s"' % day, self.body)
        for row in book.IN_PROGRESS + book.GO_LIVE:
            self.assertIn(row["title"], text)
            self.assertIn(row["text"], text)
        for row in book.LEXICON:
            self.assertIn(row["term"], text)
            self.assertIn(row["plain"], text)

    def test_every_chapter_is_in_the_contents(self):
        contents = self.body[self.body.index('id="contents"'):self.body.index("</section>", self.body.index('id="contents"'))]
        for chapter in book.CHAPTERS:
            self.assertIn('href="#%s"' % chapter["id"], contents)

    def test_the_page_parses_as_one_document(self):
        self.assertEqual(self.body.count("<section"), self.body.count("</section>"))
        self.assertTrue(self.body.rstrip().endswith("</html>"))
        self.assertNotIn("{{", self.body)
        self.assertNotIn("{%", self.body)


class TheNumbersAreCounted(TestCase):
    """Every count on the page is the Wall's own, out of core.wall_facts."""

    def _page(self, facts):
        _clear()
        with mock.patch("core.views_book.wall_facts", return_value=facts):
            return self.client.get(BOOK).content.decode("utf-8")

    def test_every_count_the_page_prints_comes_from_wall_facts(self):
        facts = _sentinels()
        body = self._page(facts)
        used = {row["key"] for row in book.HERO_STATS + book.COUNTED}
        used |= set(re.findall(r"\{([a-z_]+)\}", json.dumps(book.CHAPTERS)))
        self.assertIn("tests_green", used)
        for key in used:
            self.assertIn("{:,}".format(facts[key]), body, key)
        for row in book.HERO_STATS + book.COUNTED:
            self.assertIn('data-count="%d"' % facts[row["key"]], body, row["key"])

    def test_the_page_follows_the_facts(self):
        first = self._page(_sentinels())
        moved = {key: value + 1000 for key, value in _sentinels().items()}
        second = self._page(moved)
        self.assertIn("700,001", first)
        self.assertNotIn("700,001", second)
        self.assertIn("701,001", second)

    def test_unpatched_it_prints_the_walls_test_count(self):
        _clear()
        body = self.client.get(BOOK).content.decode("utf-8")
        self.assertIn("{:,}".format(wf.TESTS_GREEN), body)
        self.assertIn('data-count="%d"' % wf.TESTS_GREEN, body)

    def test_an_unknown_count_is_a_dash_never_a_number(self):
        facts = dict(_sentinels(), tests_green=None, bots="n/a")
        body = self._page(facts)
        self.assertEqual(body.count('data-count="None"'), 0)
        self.assertNotIn("n/a", _visible(body))
        self.assertIn("—", _visible(body))

    def test_no_number_is_typed_into_the_template(self):
        src = TEMPLATE.read_text(encoding="utf-8")
        src = re.sub(r"\{#.*?#\}|\{%.*?%\}|\{\{.*?\}\}", " ", src, flags=re.S)
        self.assertEqual(re.findall(r"\d", _visible(src)), [],
                         "a figure typed into the template will go stale like 667")

    def test_the_words_never_type_a_count_wall_facts_owns(self):
        import inspect
        src = inspect.getsource(book)
        self.assertNotIn(str(wf.TESTS_GREEN), src)
        self.assertNotIn("{:,}".format(wf.TESTS_GREEN), src)
        words = json.dumps([book.HERO, book.CHAPTERS, book.ERAS, book.MILESTONES,
                            book.IN_PROGRESS, book.GO_LIVE, book.LEXICON])
        keys = re.findall(r"\{([a-z_]+)\}", words)
        self.assertIn("tests_green", keys)
        for key in keys:
            self.assertIn(key, wf.FALLBACK_FACTS, "{%s} is not a wall_facts key" % key)

    def test_every_other_figure_is_a_dated_fact(self):
        facts = _sentinels()
        text = _visible(self._page(facts))
        for value in facts.values():
            text = text.replace("{:,}".format(value), " ")
        for pattern in (DATE_RE, DAY_RE, TIME_RE):
            text = pattern.sub(" ", text)
        stray = sorted(set(NUMBER_RE.findall(text)) - set(DATED_FIGURES))
        self.assertEqual(stray, [], "a figure with no date and no count behind it")

    def test_the_origin_figures_are_the_history(self):
        days = list(KNOWN_COMMITS.values())
        self.assertEqual(len(days), 304)
        self.assertEqual(sum(d.startswith("2026-04") for d in days), 45)
        self.assertEqual(sum(d.startswith("2026-08") for d in days), 134)
        self.assertEqual(sum(d.startswith("2026-09") for d in days), 125)
        self.assertEqual(sum(d >= "2026-08-09" for d in days), 259)
        self.assertEqual(min(days), "2026-04-05")
        origin = json.dumps(book.CHAPTERS[0])
        for figure in ("304", "45", "134", "125", "259"):
            self.assertIn(figure, origin)


class ThePublicPageKeepsItsPrivateParts(_StaffChapterOnDisk, TestCase):
    """K3: the page is served to anyone, and this repository is public.

    A staff-only chapter is on disk for every test here, so a page that
    sent it to the wrong reader would be caught with it in hand."""

    def setUp(self):
        _clear()
        self.put_chapter()
        self.body = self.client.get(BOOK).content.decode("utf-8")

    def _assert_no_staff_chapter(self, body):
        for mark in ('id="staff-chapter"', 'href="#staff-chapter"', 'lang="fr"',
                     "staff-panel", "is-staff", "family-panel", "is-family"):
            self.assertNotIn(mark, body)
        self.assertNotIn("staff", body.lower())
        for words in _fixture_words():
            self.assertNotIn(words, body)
            self.assertNotIn(html.escape(words), body)

    def test_the_anonymous_page_carries_nothing_private(self):
        self.assertEqual(_leaks(self.body), [])

    def test_the_staff_chapter_is_not_sent_to_an_anonymous_reader(self):
        self._assert_no_staff_chapter(self.body)

    def test_nor_to_a_plain_signed_in_user(self):
        self.client.force_login(User.objects.create_user("book_plain_reader", password="x"))
        body = self.client.get(BOOK).content.decode("utf-8")
        self._assert_no_staff_chapter(body)
        self.assertEqual(_leaks(body), [])
        self.assertNotIn("book_plain_reader", body)

    def test_nobody_but_staff_even_opens_the_file(self):
        with mock.patch("core.views_book.load_staff_chapter", return_value=None) as load:
            self.client.get(BOOK)
            self.client.force_login(User.objects.create_user("book_nobody", password="x"))
            self.client.get(BOOK)
            load.assert_not_called()
            self.client.force_login(User.objects.create_user("book_someone", password="x", is_staff=True))
            self.client.get(BOOK)
            load.assert_called_once_with()

    def test_staff_is_sent_the_chapter_word_for_word(self):
        self.client.force_login(User.objects.create_user("book_staff_reader", password="x", is_staff=True))
        response = self.client.get(BOOK)
        body = response.content.decode("utf-8")
        self.assertIn('id="staff-chapter"', body)
        self.assertIn('lang="fr"', body)
        self.assertIn('href="#staff-chapter"', body)
        self.assertIn("signed-in staff only", body)
        for words in _fixture_words():
            self.assertIn(html.escape(words), body)
        self.assertIn("staff-panel", body)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("private", response["Cache-Control"])
        self.assertNotIn("book_staff_reader", body)

    def test_a_superuser_is_staff_here(self):
        self.client.force_login(User.objects.create_superuser("book_su", "s@x.invalid", "x"))
        self.assertIn('id="staff-chapter"', self.client.get(BOOK).content.decode("utf-8"))

    def test_the_answer_varies_on_who_asks(self):
        self.assertIn("Cookie", self.client.get(BOOK)["Vary"])

    def test_the_walk_reads_the_head_the_style_and_the_script(self):
        """A private word typed into a comment is as public as one on the
        page: the walk finds each planted thing wherever it is put."""
        self.assertEqual(_leaks(self.body), [])
        plants = ("password", CANARY, "chat 1234567890", "ops@example.org")
        for marker in ("</style>", "</script>", "</head>"):
            for plant in plants:
                comment = "<!-- %s -->" % plant if marker == "</head>" else "/* %s */" % plant
                mutated = self.body.replace(marker, comment + marker, 1)
                self.assertNotEqual(mutated, self.body)
                self.assertTrue(_leaks(mutated), "%s in front of %s went unseen" % (plant, marker))

    def test_the_public_words_never_speak_of_private_matters(self):
        """Every string of the book's data, rendered or not, is held to the
        same lists."""
        def strings(node):
            if isinstance(node, str):
                yield node
            elif isinstance(node, dict):
                for value in node.values():
                    yield from strings(value)
            elif isinstance(node, (list, tuple)):
                for value in node:
                    yield from strings(value)
        public = [book.HERO, book.HERO_STATS, book.COUNTED, book.CHAPTERS,
                  book.ERAS, book.MILESTONES, book.IN_PROGRESS, book.GO_LIVE,
                  book.LEXICON]
        for words in strings(public):
            low = words.lower()
            for word in FORBIDDEN_WORDS:
                self.assertNotIn(word, low, words)
            self.assertEqual(_private_terms_in(words), [], words)

    def test_the_books_sources_carry_no_private_term(self):
        """The repository is public: the book's own files say none of the
        private terms either, in their text or in their comments."""
        for path in (REPO / "core" / "book_content.py", REPO / "core" / "views_book.py",
                     TEMPLATE, Path(__file__)):
            found = [gram for gram in _private_terms_in(path.read_text(encoding="utf-8"))
                     if gram != CANARY]
            self.assertEqual(found, [], path.name)
        # and the data module holds no French chapter at all
        self.assertEqual([name for name in dir(book) if name.endswith("_FR")], [])


class TheStaffChapterIsReadFromOutsideGit(_StaffChapterOnDisk, TestCase):
    """The staff-only chapter is private: never in git, read at runtime,
    word for word or not at all."""

    def setUp(self):
        _clear()
        self.client.force_login(User.objects.create_user("book_staff", password="x", is_staff=True))

    def _staff_page(self):
        response = self.client.get(BOOK)
        self.assertEqual(response.status_code, 200)
        return response.content.decode("utf-8")

    def test_the_verified_text_is_pinned(self):
        self.assertEqual(views_book.STAFF_CHAPTER_SHA256,
                         "7d66280d3431279d7f6453858589640c7d40bec75093d4b8a6188fbac70cfb1c")
        self.assertEqual(views_book.chapter_digest({"b": ["é"], "a": "x"}),
                         hashlib.sha256('{"a": "x", "b": ["é"]}'.encode("utf-8")).hexdigest())

    def test_the_file_lives_outside_git_and_inside_the_image(self):
        self.assertEqual(views_book.STAFF_CHAPTER_DEFAULT, Path("private") / "book_staff_chapter.json")
        ignored = [line.strip() for line in (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()]
        self.assertIn("/private/", ignored)
        for line in (REPO / ".dockerignore").read_text(encoding="utf-8").splitlines():
            self.assertNotIn("private", line.split("#")[0], "the image build would leave it out")

    def test_a_relative_path_is_the_projects(self):
        with mock.patch.dict(os.environ, {views_book.STAFF_CHAPTER_ENV: "private/x.json"}):
            self.assertEqual(views_book.staff_chapter_path(), REPO / "private" / "x.json")
        with mock.patch.dict(os.environ, {views_book.STAFF_CHAPTER_ENV: ""}):
            self.assertEqual(views_book.staff_chapter_path(), REPO / "private" / "book_staff_chapter.json")

    def test_without_the_file_staff_reads_the_book_without_it(self):
        with mock.patch.dict(os.environ, {views_book.STAFF_CHAPTER_ENV: str(REPO / "private" / "no-such-file.json")}):
            with self.assertNoLogs("core.views_book", "WARNING"):
                body = self._staff_page()
        self.assertNotIn('id="staff-chapter"', body)
        self.assertIn('id="closing"', body)

    def test_a_chapter_that_is_not_the_verified_text_is_not_rendered(self):
        self.put_chapter(pin=False)
        with self.assertLogs("core.views_book", "WARNING") as logs:
            body = self._staff_page()
        self.assertNotIn('id="staff-chapter"', body)
        said = " ".join(logs.output)
        self.assertIn("sha256 differs", said)
        for words in _fixture_words():
            self.assertNotIn(words, said)

    def test_a_file_that_cannot_be_read_or_is_misshapen_is_not_rendered(self):
        for raw, data in (("{not json", FIXTURE),
                          (json.dumps({"label": "x", "chapter": {"title": "t"}}), FIXTURE),
                          (json.dumps(["a list"]), FIXTURE),
                          (json.dumps(dict(FIXTURE, label="")), FIXTURE)):
            self.put_chapter(data=data, raw=raw)
            with self.assertLogs("core.views_book", "WARNING"):
                self.assertIsNone(views_book.load_staff_chapter())

    def test_the_fixture_renders_through_the_same_door(self):
        self.put_chapter()
        chapter = views_book.load_staff_chapter()
        self.assertEqual(chapter["title"], FIXTURE["chapter"]["title"])
        self.assertEqual(chapter["lang"], "fr")
        self.assertIn('id="staff-chapter"', self._staff_page())


class TheRealStaffChapterWhereItIsConfigured(SimpleTestCase):

    def test_a_real_chapter_configured_here_is_the_verified_one(self):
        """Where the private file is in place (the server, a machine it was
        copied to), it loads: a copy that drifted would render nothing."""
        if not views_book.staff_chapter_path().exists():
            self.skipTest("no staff-only chapter file on this machine")
        self.assertIsNotNone(views_book.load_staff_chapter())


class TheTextIsCleanEnglish(TestCase):

    def setUp(self):
        _clear()
        self.text = _visible(self.client.get(BOOK).content.decode("utf-8"))

    def test_no_snake_case_or_template_artefact(self):
        self.assertIsNone(re.search(r"\b[a-z]+_[a-z0-9_]+\b", self.text))
        for artefact in ("None", "undefined", "NaN", "[object", "{", "}", "&amp;", "&lt;"):
            self.assertNotIn(artefact, self.text)

    def test_it_is_english(self):
        self.assertIsNone(re.search("[àâäçéèêëîïôöùûüÿœæ]", self.text, re.I))
        low = " %s " % self.text.lower()
        for word in (" le ", " la ", " les ", " des ", " est ", " une ",
                     " pour ", " avec ", " vous ", " nous ", " dans "):
            self.assertNotIn(word, low)

    def test_every_milestone_is_one_or_two_sentences(self):
        for _day, _era, title, words, _commit in book.MILESTONES:
            self.assertLessEqual(len(re.findall(r"[.!?](?:\s|$)", words)), 2, title)
            self.assertTrue(words.endswith("."), title)

    def test_the_work_in_progress_is_said_as_in_progress(self):
        body = self.client.get(BOOK).content.decode("utf-8")
        self.assertEqual(body.count("</i>In progress</p>"), len(book.IN_PROGRESS))
        for row in book.IN_PROGRESS + book.GO_LIVE:
            for claim in (" has landed", " is live", " is done", " shipped"):
                self.assertNotIn(claim, row["text"])
        kicker = [c for c in book.CHAPTERS if c["id"] == "in-progress"][0]["kicker"]
        self.assertIn(book.WRITTEN_WORDS, kicker, "the bench is dated: it empties as batches land")


class TheRoadIsHeldToTheHistory(SimpleTestCase):

    def test_every_milestone_hash_is_in_the_history(self):
        for _day, _era, title, _words, commit in book.MILESTONES:
            self.assertRegex(commit, r"^[0-9a-f]{7}$", title)
            self.assertIn(commit, KNOWN_COMMITS, title)

    def test_every_milestone_is_dated_by_its_commit(self):
        """A milestone is dated the day it happened: its commit's day, or up
        to three days before it (the first real order of 7 September landed
        its fix on the 10th)."""
        for day, _era, title, _words, commit in book.MILESTONES:
            gap = (datetime.date.fromisoformat(KNOWN_COMMITS[commit])
                   - datetime.date.fromisoformat(day)).days
            self.assertTrue(0 <= gap <= 3, "%s: %s vs %s" % (title, day, KNOWN_COMMITS[commit]))

    def test_the_road_runs_in_order_era_by_era(self):
        order = [era["id"] for era in book.ERAS]
        days = [m[0] for m in book.MILESTONES]
        self.assertEqual(days, sorted(days))
        eras = [m[1] for m in book.MILESTONES]
        self.assertEqual(eras, sorted(eras, key=order.index))
        for era in order:
            self.assertIn(era, eras, "an era with no milestone")
        self.assertEqual(len({m[4] for m in book.MILESTONES}), len(book.MILESTONES))
        self.assertLessEqual(max(days), book.WRITTEN)

    def test_the_view_groups_them_with_their_day_in_words(self):
        eras = views_book.build(dict(wf.FALLBACK_FACTS))["eras"]
        self.assertEqual(sum(len(e["milestones"]) for e in eras), len(book.MILESTONES))
        self.assertEqual(eras[0]["milestones"][0]["day"], "5 April 2026")


class MotionIsOptional(TestCase):
    """K6: rich motion, and none of it standing between a reader and the text."""

    @classmethod
    def setUpTestData(cls):
        _clear()

    def setUp(self):
        self.body = self.client.get(BOOK).content.decode("utf-8")
        self.css = _css(self.body)

    def test_reduced_motion_stops_everything_and_shows_everything(self):
        block = _block(self.css, r"@media \(prefers-reduced-motion: reduce\)")
        self.assertIn("animation: none !important", block)
        self.assertIn("transition: none !important", block)
        self.assertIn("scroll-behavior: auto", block)
        rule = re.search(r"\[data-reveal\][^{]*\{([^}]*)\}", block).group(1)
        self.assertIn("opacity: 1 !important", rule)
        self.assertIn("transform: none !important", rule)
        head = self.body[:self.body.index("</head>")]
        script = re.search(r"<script>(.*?)</script>", head, re.S).group(1)
        self.assertIn("prefers-reduced-motion: reduce", script)
        self.assertIn('classList.add("book-js")', script)

    def test_print_shows_everything_in_dark_ink(self):
        """Printed with the script on, a page not yet scrolled through would
        otherwise come out as blank sheets."""
        block = _block(self.css, r"@media print")
        self.assertIn("animation: none !important", block)
        rule = re.search(r"\[data-reveal\][^{]*\{([^}]*)\}", block).group(1)
        self.assertIn("opacity: 1 !important", rule)
        self.assertIn("transform: none !important", rule)
        self.assertRegex(block, r"--text:\s*#111")
        self.assertRegex(block, r"\.sky, \.progress, \.bnav, \.chrail[^{]*\{\s*display: none !important")

    def test_nothing_is_hidden_unless_motion_is_welcome(self):
        css = _drop_blocks(self.css, r"@media \(prefers-reduced-motion: reduce\)")
        css = _drop_blocks(css, r"@media print")
        css = _drop_blocks(css, r"@keyframes [\w-]+")
        hiding = re.compile(r"(?<![\w-])(?:opacity\s*:\s*0(?![.\d])|visibility\s*:\s*hidden)")
        gone = re.compile(r"display\s*:\s*none")
        for selector, body in _rules(css):
            parts = [p.strip() for p in selector.split(",")]
            if hiding.search(body):
                for part in parts:
                    self.assertTrue(part.startswith(".book-js") or part.endswith(("::before", "::after")),
                                    "%s hides content without the motion switch" % part)
            if gone.search(body):
                for part in parts:
                    self.assertIn(part, (".chrail", ".bnav-num:empty", ".bnav-word"), part)

    def test_the_markup_arrives_unrevealed_and_complete(self):
        self.assertRegex(self.body, r"<html lang=\"en\">")
        self.assertNotIn("is-in", re.sub(r"<(style|script)\b.*?</\1>", "", self.body, flags=re.S))
        self.assertIsNone(re.search(r"style=\"[^\"]*opacity\s*:\s*0", self.body))
        head = self.body[:self.body.index("</head>")]
        self.assertIn("bookAwake", head)
        self.assertIn("setTimeout", head)
        self.assertIn('classList.remove("book-js")', head)
        for m in re.finditer(r'data-count="(\d+)">([^<]*)<', self.body):
            self.assertEqual(m.group(2), "{:,}".format(int(m.group(1))),
                             "a counted number is printed as something else before the script runs")

    def test_the_motion_moves_only_transform_and_opacity(self):
        for m in re.finditer(r"@keyframes ([\w-]+)", self.css):
            frames = _block(self.css[m.start():], r"@keyframes [\w-]+")
            for _sel, body in _rules(frames):
                for prop in re.findall(r"([\w-]+)\s*:", body):
                    self.assertIn(prop, ("transform", "opacity"), "@keyframes %s animates %s" % (m.group(1), prop))

    def test_no_animation_runs_on_a_shape_inside_an_svg(self):
        """A transform or opacity animated on a <g>, <circle> or <line> is
        repainted on the main thread every frame; each moving part is its
        own <svg> or box, which the compositor moves."""
        shapes = {"g", "circle", "ellipse", "path", "line", "rect", "polygon",
                  "polyline", "text", "use", "stop"}
        tags_of = {}
        for m in re.finditer(r"<([a-zA-Z][\w-]*)\b[^>]*?\bclass=\"([^\"]*)\"", self.body):
            for name in m.group(2).split():
                tags_of.setdefault(name, set()).add(m.group(1).lower())
        css = _drop_blocks(self.css, r"@keyframes [\w-]+")
        checked = 0
        for selector, body in _rules(css):
            if not re.search(r"(?:^|;)\s*animation(?:-name)?\s*:\s*(?!none)", body):
                continue
            for part in selector.split(","):
                subject = re.sub(r":not\([^)]*\)", "", part.strip().split()[-1])
                subject = re.sub(r"::?[\w-]+(?:\([^)]*\))?", "", subject)
                tag = re.match(r"[a-z]+", subject)
                self.assertFalse(tag and tag.group(0) in shapes, part)
                for name in re.findall(r"\.([\w-]+)", subject):
                    checked += 1
                    self.assertFalse(tags_of.get(name, set()) & shapes,
                                     "%s animates a shape inside an <svg>" % part)
        self.assertGreater(checked, 20)
        for name in ("gl-look", "gl-gear", "gl-lamp", "gl-node", "gl-sheet", "gl-dotb",
                     "iris-mer", "loop-spin", "pupil"):
            self.assertEqual(tags_of.get(name), {"svg"}, name)

    def test_a_chapter_label_never_stands_over_the_page(self):
        """The rail's labels show on hover or focus only: the chapter being
        read is named by the pill in the bar."""
        self.assertIsNone(re.search(r"is-active[^{},]*\.chrail-lbl", self.css))
        self.assertRegex(self.css, r"\.chrail a:hover \.chrail-lbl")

    def test_the_openings_counts_wait_for_their_entrance(self):
        script = re.findall(r"<script>(.*?)</script>", self.body, re.S)[1]
        self.assertIn("function afterEntrance(el, go)", script)
        self.assertIn("getAnimations", script)
        self.assertIn("afterEntrance(el, function () { climb(el); })", script)
        self.assertRegex(self.css, r"\.book-js \.stats \{ animation: rise")

    def test_the_sky_rests_when_the_page_is_still(self):
        script = re.findall(r"<script>(.*?)</script>", self.body, re.S)[1]
        self.assertIn("RESTING_AFTER", script)
        self.assertIn("window.setTimeout(function () { raf(skyFrame); }, RESTING_GAP)", script)

    def test_the_motion_is_all_there(self):
        for mark in ('id="bookEyeLook"', "iris-fibres", "iris-ticks", "iris-mer", "iris-scan", "pupil",
                     "eye-halo", "eye-rays", 'id="bookSky"', 'class="progress"', "data-count",
                     "data-reveal", "data-stagger", "data-circuit", "data-timeline", "tl-rail-fill",
                     "tl-era-head", "data-tilt", "data-now-label", "chrail", "IntersectionObserver",
                     "circuit-pulse", "requestAnimationFrame", "position: sticky"):
            self.assertIn(mark, self.body, mark)

    def test_the_scripts_are_plain_so_the_parse_sweep_reads_them(self):
        """tests/test_inline_js_parses.py checks every inline block that
        carries no template tag; both of the book's are that kind."""
        blocks = re.findall(r"<script>(.*?)</script>", self.body, re.S)
        self.assertEqual(len(blocks), 2)
        src = TEMPLATE.read_text(encoding="utf-8")
        for block in re.findall(r"<script>(.*?)</script>", src, re.S):
            self.assertIsNone(re.search(r"\{%|\{\{", block))


class PhoneFirst(TestCase):

    def setUp(self):
        _clear()
        self.body = self.client.get(BOOK).content.decode("utf-8")
        self.css = _css(self.body)

    def test_it_fits_a_phone(self):
        self.assertIn('name="viewport" content="width=device-width, initial-scale=1.0', self.body)
        self.assertIn("overflow-x: clip", self.css)
        for width in re.findall(r"(?<![-\w])width\s*:\s*(\d+)px", self.css):
            self.assertLessEqual(int(width), 300, "a fixed width wider than a phone's column")
        for track in re.findall(r"repeat\(auto-fill,\s*minmax\(([^)]*\))", self.css):
            self.assertTrue(track.startswith("min(100%,"), track)
        self.assertNotIn("prefers-color-scheme: light", self.css)

    def test_on_a_phone_the_way_back_leaves_the_pill_its_room(self):
        """Under 420 px the Wall link keeps its arrow and says its words to
        a screen reader only, so the chapter pill can name the chapter."""
        block = _block(self.css, r"@media \(max-width: 420px\)")
        rule = re.search(r"\.bnav-back-word\s*\{([^}]*)\}", block).group(1)
        self.assertIn("clip-path: inset(50%)", rule)
        self.assertNotIn("display: none", rule)
        self.assertIn('<span class="bnav-back-word">The Wall</span>', self.body)

    def test_the_small_words_are_readable(self):
        """Labels and notes are set in the second text colour (7.6:1 on the
        page), not the third (3.2:1), which stays for ornament."""
        for selector in (".hero-sub", ".stat-l", ".cue", ".ch-note", ".counted-l",
                         ".closing-sign", ".bfoot-text", ".bfoot-note"):
            rule = re.search(r"(?<![\w-])%s\s*\{([^}]*)\}" % re.escape(selector), self.css).group(1)
            self.assertIn("color: var(--text2)", rule, selector)


class TheProbeWalksIt(SimpleTestCase):

    def test_the_route_is_in_the_probes_walk(self):
        from core.management.commands.probe_routes import MUTATING, free_routes
        self.assertIn(("the_book", "book/", True), free_routes())
        self.assertIsNone(MUTATING.search("the_book"))
