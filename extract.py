#!/usr/bin/env python3
"""
extract.py — Step 1 of Practical Projector: pull every picture out of /source into /bank.

    python3 extract.py                 # extract new pictures from /source into /bank
    python3 extract.py --apply         # apply your fixes from corrections.csv (move / rename / delete)
    python3 extract.py --fresh         # throw away everything extract.py made before and start again

What it does
  * Extracts embedded images from PDF, PowerPoint (.pptx) and Word (.docx) files, zips (also nested),
    and copies loose images (jpg/png/webp/heic/...) -> jpg.  Old .ppt/.doc files are converted first
    if LibreOffice is installed.
  * Finds a label for each image (slide title, caption, heading or nearest text).
  * Removes duplicates with perceptual hashing (resized / recompressed / slightly cropped copies match),
    keeps the highest-resolution copy, the best label, and merges questions/notes from every copy.
  * Skips junk: logos repeated on many pages, icons, tiny images, blank / near-solid images.
  * Sorts into bank/<Course>/<Category>/ (or _Unsorted), guesses the type (slide / pot / photomicrograph),
    and writes a sidecar JSON with the label, type and any questions found next to the image.
  * Writes extract-report.html (check and fix everything) and corrections.csv.
  * Runs `node build-bank.js` at the end (if Node is installed).

Running it again only ADDS new pictures. Pictures already in /bank are never overwritten, so your
renames, moves and question files are safe. (A better copy of an existing picture replaces the image
pixels only, and new questions are merged into its JSON.)

Requirements:  pip install pymupdf pillow        (optional: pillow-heif for iPhone .heic photos)
"""

import argparse
import csv
import datetime
import hashlib
import html
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import zipfile
from xml.etree import ElementTree as ET

try:
    from PIL import Image, ImageOps
except ImportError:
    sys.exit("Pillow is missing. Install it with:  pip install pillow pymupdf")

Image.MAX_IMAGE_PIXELS = 200_000_000

try:
    import pymupdf  # PyMuPDF >= 1.24
except ImportError:
    try:
        import fitz as pymupdf  # older PyMuPDF
    except ImportError:
        pymupdf = None

HEIC_OK = False
try:
    import pillow_heif  # type: ignore

    pillow_heif.register_heif_opener()
    HEIC_OK = True
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
SOURCE_DIR = os.path.join(ROOT, "source")
BANK_DIR = os.path.join(ROOT, "bank")
MANIFEST = os.path.join(ROOT, "extract-manifest.json")
CORRECTIONS = os.path.join(ROOT, "corrections.csv")
REPORT = os.path.join(ROOT, "extract-report.html")
REJECTS_DIR = os.path.join(ROOT, "extract-rejects")
TRASH_DIR = os.path.join(ROOT, "extract-trash")
CACHE = os.path.join(ROOT, ".extract-cache.json")

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".jfif", ".avif"}
BANK_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}
PPT_EXT = {".pptx", ".pptm", ".ppsx", ".potx"}
DOC_EXT = {".docx", ".docm", ".dotx"}
OLD_OFFICE = {".ppt": "pptx", ".pps": "pptx", ".doc": "docx", ".rtf": "docx", ".odt": "docx", ".odp": "pptx"}

MIN_SIDE = 200  # skip images smaller than this on the short side
MAX_SIDE = 2000  # downscale saved images to this long side (plenty for a projector)

# ----------------------------------------------------------------------------- courses & categories

COURSES = ["Histopathology", "Chemical Pathology", "MMP", "Haematology"]
COURSE_ALIASES = [
    ("Chemical Pathology", r"chem|clinical\s*bio|biochem"),
    ("Histopathology", r"histo|morbid|anatomic|^path"),
    ("MMP", r"mmp|micro|parasit|bacter|virol"),
    ("Haematology", r"ha?em|blood"),
]

# Order matters: the first category with the most keyword hits wins. "=word" means whole word only.
CATEGORIES = {
    "Histopathology": [
        ("Liver", "liver hepat cirrho cholangio =hcc hepatoma hepatitis"),
        ("Gallbladder & Pancreas", "gallbladder gall-bladder cholecyst gallstone pancrea"),
        ("Kidney", "kidney renal nephr glomerul pyelo wilms hydroneph"),
        ("Urinary Bladder", "bladder urothel cystitis =transitional"),
        ("Lung", "lung pulmon pneumon bronch emphysem asbest pleura =tb tubercul"),
        ("Heart & Blood Vessels", "heart cardi myocard endocard pericard valv rheumatic aort aneurysm atheros arter vascul varicose"),
        ("Gastrointestinal Tract", "oesophag esophag stomach gastr peptic intestin bowel colon colorect rect appendi duoden ileum ileal jejun polyp crohn colitis typhoid"),
        ("Breast", "breast mammary fibroadenoma phyllodes gynaecomast gynecomast"),
        ("Female Genital Tract", "uter cervi ovar endometr leiomyom fibroid hydatidiform =mole chorioca placent fallop salping ectopic vulv vagin teratoma"),
        ("Male Genital Tract", "testi prostat seminoma penis penile scrot epididym"),
        ("Thyroid & Endocrine", "thyroid goitre goiter adrenal pituit parathyroid"),
        ("Central Nervous System", "brain cerebr mening glioma astrocyt hydroceph spinal neuro"),
        ("Bone & Soft Tissue", "bone osteo sarcoma chondro lipoma fibroma ewing muscle =joint"),
        ("Skin", "skin melanom basal keloid naev nevus kaposi derm"),
        ("Lymph Node & Spleen", "lymph spleen splen hodgkin burkitt"),
        ("Head & Neck", "salivary parotid pleomorphic nasopharyn =oral tongue =jaw ameloblast"),
        ("General Pathology", "inflamm necros granulom amyloid calcif infarct gangren abscess apoptosis fatty metaplas dysplas hyperplas atroph wound repair thromb embol oedema edema"),
    ],
    "Chemical Pathology": [
        ("Calculi", "calcul =stone =stones staghorn"),
        ("Urinalysis", "urine urinaly dipstick combur urinometer clinitest acetest"),
        ("Specimen Containers", "bottle container vacutainer =tube =tubes fluoride oxalate edta heparin =cap universal"),
        ("Equipment", "centrifug spectrophotomet colorimet photomet analy pipett glucomet glucomet =balance water-bath =oven refractomet =ph osmomet incubat microscop cuvett"),
        ("Charts & Electrophoresis", "electrophor chart graph curve =gtt ogtt tolerance levey westgard =plot"),
        ("Clinical Signs", "xanthelasma xanthoma arcus kwashiorkor marasmus cushing acromegal tetany gout tophi jaundice exophthalm myxoedema goitre goiter rickets"),
    ],
    "MMP": [
        ("Vectors & Arthropods", "mosquito anopheles aedes culex tsetse glossina simulium blackfly =tick =ticks =mite =mites louse =lice flea sandfly chrysops snail cyclops triatom vector"),
        ("Fungi", "fung candida yeast aspergill cryptococ mucor dermatophyt tinea trichophyt microspor histoplasm hyphae india-ink madura mycetoma pneumocystis"),
        ("Parasites", "plasmod malaria trypanosom leishman entamoeba giardia trichomon schistosom ascaris hookworm ancylostom necator strongyl trichuris whipworm enterobius taenia tapeworm echinococ hydatid filari =loa onchocerc wuchereria =ova =egg =eggs =cyst =cysts trophozoite worm helminth protozo fasciola toxoplasm dracunc parasite"),
        ("Viruses", "virus viral =hiv herpes measles polio rabies negri influenza ebola lassa varicella smallpox inclusion virion dengue yellow-fever rota corona"),
        ("Culture Media", "agar media medium culture macconkey chocolate lowenstein sabouraud coloni =plate =plates broth slope"),
        ("Bacteria", "bacteri coccus cocci bacill =gram staphylo strepto pneumococ neisseria gonococ meningococ mycobacter tubercle =afb ziehl salmonella shigella coli escherichia klebsiella proteus pseudomonas vibrio cholera clostrid coryne diphther treponema spiroch leptospir haemophilus listeria yersinia brucella chlamydia rickett"),
        ("Lab Equipment & Techniques", "autoclave incubat microscop =loop swab petri bunsen anaerob sensitivity antibiotic coagulase catalase =api"),
    ],
    "Haematology": [
        ("Bone Marrow", "marrow trephine aspirat"),
        ("Blood Transfusion", "transfusion blood-bag grouping cross-match crossmatch =abo rhesus coombs antiglobulin donor cpda"),
        ("White Cell Disorders", "leuk leuc lymphoma myeloma =blast blasts auer myelo lymphocyt neutrophil eosinophil basophil monocyt hypersegment smudge hairy plasma granulocyt"),
        ("Platelets & Coagulation", "platelet thrombocyt coagul bleeding =clot haemophil hemophil =factor purpura =ptt prothrombin fibrin =dic willebrand"),
        ("Red Cell Disorders", "anaemi anemi sickle target spherocyt elliptocyt hypochrom microcyt macrocyt megaloblast thalass reticulocyt poikilocyt schistocyt howell stippl rouleaux polycyth g6pd heinz =red erythro"),
        ("Equipment", "centrifug haematocrit hematocrit =pcv haemocytomet hemocytomet neubauer counting westergren =esr wintrobe sahli haemoglobinomet lancet pipett analy microscop cuvett capillary sealant"),
        ("Specimen Bottles", "edta citrate bottle =tube =tubes vacutainer"),
    ],
}


def _compile_categories():
    out = {}
    for course, cats in CATEGORIES.items():
        lst = []
        for name, words in cats:
            pats = []
            for w in words.split():
                w = w.replace("-", "[ -]?")
                if w.startswith("="):
                    pats.append(r"\b" + w[1:] + r"\b")
                else:
                    pats.append(r"\b" + w)
            lst.append((name, re.compile("|".join(pats), re.I)))
        out[course] = lst
    return out


CAT_RE = _compile_categories()


def canonical_course(folder_name):
    n = folder_name.strip().lower()
    for c in COURSES:
        if n == c.lower():
            return c
    for c, pat in COURSE_ALIASES:
        if re.search(pat, n):
            return c
    return folder_name.strip()


def match_categories(course, text):
    """Return {category: hits} for one piece of text."""
    if not text or course not in CAT_RE:
        return {}
    hits = {}
    for name, rx in CAT_RE[course]:
        n = len(rx.findall(text))
        if n:
            hits[name] = n
    return hits


def pick_category(course, hints):
    """hints: list of (text, strict). The first hint that names a category wins.
    strict=True (e.g. whole-page text) only counts when one category clearly dominates."""
    order = {name: i for i, (name, _) in enumerate(CAT_RE.get(course, []))}
    for text, strict in hints:
        hits = match_categories(course, text)
        if not hits:
            continue
        ranked = sorted(hits.items(), key=lambda kv: (-kv[1], order.get(kv[0], 99)))
        if strict and len(ranked) > 1 and ranked[0][1] < 2 * ranked[1][1]:
            continue
        return ranked[0][0]
    return "_Unsorted"


def guess_type(course, text):
    t = (text or "").lower()
    if re.search(r"photo\s*-?micrograph|micrograph", t):
        return "photomicrograph"
    if re.search(r"\bpots?\b|\bgross\b|museum|\bjar\b|cut surface|resect|excis|specimen of|bisected|\bsliced\b", t):
        return "pot"
    if course == "Histopathology" and re.search(r"\bspecimen\b", t) and not re.search(r"slide|section", t):
        return "pot"
    if re.search(r"h\s*&\s*e|\bh and e\b|haematoxylin|hematoxylin|[x×]\s?\d{2,4}\b|\d{2,4}\s?[x×]\b|\bsection\b|\bslide\b|"
                 r"high power|low power|\bhpf\b|\blpf\b|oil immersion|magnification|\bstain|giemsa|leishman|\bgram\b|ziehl|"
                 r"\bpas\b|\bfilm\b|\bsmear\b|microscop", t):
        return "slide"
    return ""


# ----------------------------------------------------------------------------- text helpers

GENERIC_RE = re.compile(
    r"^(spot(ter)?|station|slide|question|q|figure|fig|image|img|picture|pic|plate|photo|specimen|pot|answer|ans|"
    r"unknown|untitled|title|click to add (title|text)|identify( (this|the) \w+)?|next|thank you|thanks|references?|"
    r"outline|introduction|objectives?|contents?|summary|conclusion|questions?|practical|spotters?|test|quiz|exam|"
    r"department of .*|college of .*|university of .*|faculty of .*|school of .*|lecture.*)\s*[\d.:)\-–]*$",
    re.I,
)
PREFIX_RE = re.compile(r"^\s*((fig(ure)?|plate|slide|spot(ter)?|station|image|pic(ture)?|photo|specimen|pot|q(uestion)?)"
                       r"\s*(no\.?)?\s*\d*[a-z]?\s*[.:)\-–]+\s*|\d{1,3}\s*[.):\-–]\s+)", re.I)
MAG_RE = re.compile(r"\(([^)]*(h\s*&\s*e|[x×]\s?\d+|\d+\s?[x×]|stain|magnif|power|giemsa|leishman|gram|gross|\bpots?\b|specimen|section|slide|micrograph|museum)[^)]*)\)", re.I)
Q_START_RE = re.compile(
    r"^\s*(?:(?:q(?:uestion)?\s*\d*\s*[.):\-–]?\s*)|(?:\d{1,2}\s*[.)]\s*)|(?:\(?[a-h]\s*[.)]\s*)|(?:\(?[ivx]{1,4}\s*[.)]\s*))?"
    r"(identify|name|give|list|state|mention|what|which|describe|outline|enumerate|label|explain|how|why|define|"
    r"comment|write|suggest|highlight|indicate|enumerate|classify|differentiate|tabulate)\b",
    re.I,
)
IDENTIFY_RE = re.compile(r"\s*(identify|spot|what is (this|the) (specimen|slide|pot|organism|lesion)|"
                         r"name (the|this) (specimen|slide|organism|lesion|pot|parasite|item|equipment))\b", re.I)
ANS_RE = re.compile(r"^\s*(?:ans(?:wers?)?|a|key)\s*[:.\-–]\s*(.+)$", re.I)
INLINE_ANS_RE = re.compile(r"\s(?:ans(?:wers?)?|answer)\s*[:\-–]\s*", re.I)
CAMERA_NAME_RE = re.compile(
    r"^(img|dsc|dscn|dcim|pxl|mvimg|photo|image|screenshot|screen shot|whatsapp|wa\d|snapchat|fb_img|received|"
    r"signal|telegram|pic|picture|scan|cam|camera|untitled|download|unnamed|unlabel+ed)[\W_\d]|^[\W_\d]+$|^[0-9a-f]{16,}$",
    re.I,
)


def squash(t):
    return re.sub(r"\s+", " ", (t or "").replace(" ", " ")).strip()


def norm(t):
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def is_question(line):
    line = line.strip()
    return bool(line) and (bool(Q_START_RE.match(line)) or (line.endswith("?") and len(line) > 6))


def clean_label(text):
    """Turn a caption/title into a label, or None if it does not look like one."""
    t = squash(text)
    if not t:
        return None
    t = re.sub(r"^[••·\-–*>»▪◦●○■□➢✓✔]+\s*", "", t)
    for _ in range(2):
        t = PREFIX_RE.sub("", t).strip()
    t = MAG_RE.sub("", t)
    t = re.sub(r"\b(h\s*&\s*e|[x×]\s?\d{2,4}|\d{2,4}\s?[x×])\b\s*(stain(ed)?)?", "", t, flags=re.I)
    t = re.sub(r"[\s,\-–:]+(gram|giemsa|leishman|ziehl[- ]?neelsen|zn|pas|india ink|lactophenol cotton blue|wright'?s?|"
               r"field'?s?|iodine|saline)\s*(stain(ed)?|preparation|prep|mount)?\s*$", "", t, flags=re.I)
    t = re.sub(r"\s*[,;:.\-–]+\s*$", "", t).strip(" -–:;,.\"'")
    t = squash(t)
    if len(t) < 3 or len(t) > 90 or len(t.split()) > 12:
        return None
    if GENERIC_RE.match(t) or is_question(t) or ANS_RE.match(t):
        return None
    if not re.search(r"[A-Za-z]{3}", t):
        return None
    if t.isupper() and len(t) > 4:
        t = t.capitalize()
    return t[0].upper() + t[1:]


def label_from_filename(name):
    base = os.path.splitext(os.path.basename(name))[0]
    if CAMERA_NAME_RE.match(base):
        return None
    base = re.sub(r"[_]+|(?<=[a-z])-(?=[a-z])", " ", base)
    base = re.sub(r"\s*\(\d+\)$|\s+copy$|\s+\d{1,3}$", "", base, flags=re.I)
    return clean_label(base)


def parse_qa(lines):
    """Pull questions (and answers if given) out of text lines. Returns (questions, notes)."""
    questions, notes = [], []
    for raw in lines:
        line = squash(raw)
        if not line or len(line) < 3:
            continue
        m = ANS_RE.match(line)
        if m and questions and not questions[-1]["a"]:
            questions[-1]["a"] = m.group(1).strip()
            continue
        if is_question(line):
            parts = INLINE_ANS_RE.split(line, maxsplit=1)
            q = re.sub(r"^\s*(?:q(?:uestion)?\s*\d*\s*[.):\-–]?\s*|\d{1,2}\s*[.)]\s*|\(?[a-h]\s*[.)]\s*|\(?[ivx]{1,4}\s*[.)]\s*)", "",
                       parts[0], flags=re.I).strip()
            if len(q) >= 4:
                questions.append({"q": q[0].upper() + q[1:], "a": parts[1].strip() if len(parts) > 1 else ""})
            continue
        if len(line) <= 300 and not GENERIC_RE.match(line):
            notes.append(line)
    return questions, notes


def slugify(label):
    s = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return (s[:60].rstrip("-")) or "image"


# ----------------------------------------------------------------------------- image helpers

_COS = [[math.cos((2 * x + 1) * u * math.pi / 64) for x in range(32)] for u in range(8)]


def _phash_from_gray(g):
    """g: 32x32 'L' image -> 64-bit pHash (top-left 8x8 DCT, median threshold). Pure Python, separable DCT."""
    px = list(g.tobytes())
    rows = [px[y * 32:(y + 1) * 32] for y in range(32)]
    tmp = [[sum(c * v for c, v in zip(_COS[u], row)) for u in range(8)] for row in rows]  # 32 x 8
    coeffs = []
    for v in range(8):
        cv = _COS[v]
        for u in range(8):
            coeffs.append(sum(cv[y] * tmp[y][u] for y in range(32)))
    body = coeffs[1:]
    med = sorted(body)[len(body) // 2]
    bits = 0
    for c in coeffs:
        bits = (bits << 1) | (1 if c > med else 0)
    return bits


# Cropped versions used to catch slightly cropped copies: (left, top, right, bottom) fractions kept.
CROPS = [(.03, .03, .97, .97), (.05, .05, .95, .95), (.075, .075, .925, .925), (.1, .1, .9, .9), (.15, .15, .85, .85),
         (.1, 0, 1, 1), (0, 0, .9, 1), (0, .1, 1, 1), (0, 0, 1, .9), (0, .15, 1, 1), (0, 0, 1, .85),
         (.06, .06, 1, 1), (0, 0, .94, .94)]


def image_hashes(im):
    g = im.convert("L")
    if max(g.size) > 256:  # hashes only need a small copy; much faster
        g = g.copy()
        g.thumbnail((256, 256), Image.BILINEAR)
    w, h = g.size
    ph = _phash_from_gray(g.resize((32, 32), Image.LANCZOS))
    variants = []
    for l, t, r, b in CROPS:
        crop = g.crop((int(w * l), int(h * t), int(w * r), int(h * b)))
        variants.append(_phash_from_gray(crop.resize((32, 32), Image.LANCZOS)))
    d = list(g.resize((9, 8), Image.LANCZOS).tobytes())
    dh = 0
    for y in range(8):
        for x in range(8):
            dh = (dh << 1) | (1 if d[y * 9 + x] > d[y * 9 + x + 1] else 0)
    small = im.convert("RGB").resize((1, 1), Image.BOX).getpixel((0, 0))
    return {"ph": ph, "v": variants, "dh": dh, "rgb": list(small)}


if hasattr(int, "bit_count"):  # Python 3.10+
    def hamming(a, b):
        return (a ^ b).bit_count()
else:
    def hamming(a, b):
        return bin(a ^ b).count("1")


def is_duplicate(a, b):
    """True if b looks like a copy of a (resized, recompressed, recoloured or slightly cropped)."""
    p = hamming(a["ph"], b["ph"])
    if p <= 4:
        return True
    color = sum(abs(x - y) for x, y in zip(a["rgb"], b["rgb"]))
    if color > 75:
        return False
    dh = hamming(a["dh"], b["dh"])
    if (p <= 8 and dh <= 14) or (p <= 12 and dh <= 6):
        return True
    if p > 40:  # completely different picture: skip the slower crop checks
        return False
    pa, pb = a["ph"], b["ph"]
    return any(hamming(pa, v) <= 6 for v in b.get("v", ())) or any(hamming(pb, v) <= 6 for v in a.get("v", ()))


def to_rgb(im):
    im = ImageOps.exif_transpose(im) if hasattr(ImageOps, "exif_transpose") else im
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        return bg
    if im.mode == "CMYK":
        return ImageOps.invert(im.convert("RGB")) if im.info.get("adobe_inverted") else im.convert("RGB")
    return im.convert("RGB")


def junk_reason(im, raw_mode=None):
    w, h = im.size
    if min(w, h) < MIN_SIDE:
        return f"too small ({w}×{h})"
    if max(w, h) / max(1, min(w, h)) > 6:
        return f"banner/line shape ({w}×{h})"
    g = im.convert("L").resize((64, 64))
    px = list(g.tobytes())
    mean = sum(px) / len(px)
    sd = math.sqrt(sum((p - mean) ** 2 for p in px) / len(px))
    if sd < 7:
        return "blank / near-solid"
    if raw_mode in ("1",) and min(w, h) < 600:
        return "black-and-white graphic"
    q = im.convert("RGB").resize((64, 64), Image.NEAREST)
    counts = {}
    raw = q.tobytes()
    for i in range(0, len(raw), 3):
        k = (raw[i] >> 3, raw[i + 1] >> 3, raw[i + 2] >> 3)
        counts[k] = counts.get(k, 0) + 1
    # Flat-colour artwork (logos, crests, icons) has very few colours; photos have hundreds.
    # Only small ones are rejected, so big charts/diagrams (e.g. Chem Path graphs) are kept.
    if len(counts) < 40 and min(w, h) < 500:
        return "icon / logo / graphic"
    return None


def open_image_bytes(data):
    im = Image.open(io.BytesIO(data))
    im.load()
    return im


# ----------------------------------------------------------------------------- candidate collection

class Collector:
    def __init__(self, workdir, verbose=False):
        self.work = workdir
        self.cands = []
        self.rejects = []
        self.errors = []
        self.verbose = verbose
        self.n = 0

    def log(self, msg):
        if self.verbose:
            print("   " + msg)

    def add(self, data_or_img, ctx):
        """ctx: course, source, where, label (str|None), label_src, hints [(text,strict)], type_text, questions, notes,
        repeat (int pages the same picture appears on in this file), area_frac (picture area / page area or None)"""
        try:
            raw = data_or_img if isinstance(data_or_img, Image.Image) else open_image_bytes(data_or_img)
            raw_mode = raw.mode
            im = to_rgb(raw)
        except Exception as e:
            self.errors.append(f"{ctx['source']} {ctx.get('where', '')}: could not read an image ({e.__class__.__name__})")
            return
        self.n += 1
        reason = junk_reason(im, raw_mode)
        rep = ctx.get("repeat", 1)
        if not reason and looks_like_logo(rep, ctx.get("area_frac")) and min(im.size) < 700:
            reason = f"logo / crest (repeats on {rep} pages)"
        if reason:
            self.reject(im, ctx, reason)
            return
        path = os.path.join(self.work, f"c{len(self.cands):05d}.png" if im.size[0] * im.size[1] < 250_000 else f"c{len(self.cands):05d}.jpg")
        if path.endswith(".jpg"):
            im.save(path, quality=95)
        else:
            im.save(path)
        c = dict(ctx)
        c.update({"path": path, "w": im.size[0], "h": im.size[1], "bytes": os.path.getsize(path)})
        c.update(image_hashes(im))
        self.cands.append(c)

    def reject(self, im, ctx, reason, dup_of=None):
        thumb = None
        try:
            os.makedirs(REJECTS_DIR, exist_ok=True)
            t = im.copy()
            t.thumbnail((240, 240))
            thumb = f"r{len(self.rejects):05d}.jpg"
            t.save(os.path.join(REJECTS_DIR, thumb), quality=70)
        except Exception:
            pass
        self.rejects.append({"thumb": thumb, "reason": reason, "source": ctx.get("source", ""), "where": ctx.get("where", ""),
                             "label": ctx.get("label") or "", "dup_of": dup_of})


def looks_like_logo(repeat, area_frac):
    return repeat >= 3 and (area_frac is None or area_frac < 0.2)


def nearest_text(img_box, texts, page_h):
    """texts: [(text, (x0,y0,x1,y1))]. Return texts sorted by closeness to the picture (captions first)."""
    if not img_box:
        return []
    x0, y0, x1, y1 = img_box
    scored = []
    for t, (a0, b0, a1, b1) in texts:
        overlap = min(x1, a1) - max(x0, a0)
        width = max(1.0, min(x1 - x0, a1 - a0))
        if b0 >= y1 - 2:
            gap = b0 - y1
        elif b1 <= y0 + 2:
            gap = (y0 - b1) * 1.3  # text above is slightly less likely to be the caption
        else:
            gap = 0 if overlap > 0 else min(abs(a0 - x1), abs(x0 - a1)) * 1.5
        if overlap < -0.1 * width and gap > 0:
            gap += abs(overlap) * 1.5
        if gap > 0.3 * page_h:
            continue
        scored.append((gap, t))
    scored.sort(key=lambda s: s[0])
    return [t for _, t in scored]


def choose_label(options):
    labels = [(clean_label(t), src) for t, src in options]
    labels = [(l, src) for l, src in labels if l]
    if not labels:
        return None, "none"
    first, src = labels[0]
    # A short title like "Cirrhosis" loses to a caption that says more ("Cirrhosis of the liver").
    for lab, s2 in labels[1:]:
        if norm(first) and len(lab) > len(first) and re.search(r"\b" + re.escape(norm(first)) + r"\b", norm(lab)):
            return lab, s2
    return first, src


def same_label(line, label):
    """True if this text line is just the label (so it should not also become a note)."""
    if not label:
        return False
    cl = clean_label(line)
    return bool(cl) and (norm(cl) == norm(label) or norm(label) in norm(cl))


# ---- PDF

def process_pdf(col, path, base_ctx):
    if pymupdf is None:
        col.errors.append(f"{base_ctx['source']}: PyMuPDF not installed (pip install pymupdf) — PDF skipped")
        return
    try:
        doc = pymupdf.open(path)
    except Exception as e:
        col.errors.append(f"{base_ctx['source']}: could not open PDF ({e})")
        return
    # how many pages each image appears on (logos/crests repeat)
    pages_of = {}
    for pno in range(len(doc)):
        try:
            for img in doc[pno].get_images(full=True):
                pages_of.setdefault(img[0], set()).add(pno)
        except Exception:
            pass
    section = ""
    for pno in range(len(doc)):
        page = doc[pno]
        pw, ph_ = page.rect.width, page.rect.height
        lines = []
        try:
            d = page.get_text("dict")
            for b in d.get("blocks", []):
                if b.get("type") != 0:
                    continue
                for ln in b.get("lines", []):
                    txt = squash("".join(s.get("text", "") for s in ln.get("spans", [])))
                    if not txt:
                        continue
                    size = max((s.get("size", 0) for s in ln.get("spans", [])), default=0)
                    lines.append((txt, tuple(ln["bbox"]), size))
        except Exception:
            pass
        # merge consecutive lines of the same block into caption-sized chunks
        texts = [(t, bb) for t, bb, _ in lines]
        sizes = sorted(s for _, _, s in lines)
        med = sizes[len(sizes) // 2] if sizes else 0
        title = ""
        big = [(bb[1], t) for t, bb, s in lines if s >= med * 1.25 and bb[1] < ph_ * 0.35]
        if big:
            big.sort()
            title = big[0][1]
        elif lines and lines[0][1][1] < ph_ * 0.2:
            title = lines[0][0]
        imgs = page.get_images(full=True)
        if not imgs and lines and len(lines) <= 3 and title:
            section = title
        page_text = " ".join(t for t, _, _ in lines)
        seen = set()
        placed = []
        for img in imgs:
            xref = img[0]
            if xref in seen:
                continue
            seen.add(xref)
            try:
                rects = page.get_image_rects(xref)
            except Exception:
                rects = []
            box = tuple(rects[0]) if rects else None
            area_frac = ((box[2] - box[0]) * (box[3] - box[1]) / (pw * ph_)) if box else None
            if area_frac is not None and area_frac < 0.002:
                continue  # invisible / bullet-sized placement
            data = None
            try:
                info = doc.extract_image(xref)
                if info and info.get("ext") in ("jpeg", "jpg", "png", "bmp", "gif", "tiff", "webp") and not info.get("smask"):
                    data = info["image"]
                    open_image_bytes(data)
            except Exception:
                data = None
            if data is None:
                try:
                    pix = pymupdf.Pixmap(doc, xref)
                    if pix.n - pix.alpha >= 4:
                        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                    if pix.alpha:
                        pix = pymupdf.Pixmap(pix, 0)
                    data = pix.tobytes("png")
                except Exception as e:
                    col.errors.append(f"{base_ctx['source']} page {pno + 1}: image could not be decoded ({e.__class__.__name__})")
                    continue
            placed.append((box, area_frac, data, len(pages_of.get(xref, ()))))
        multi = sum(1 for b, af, _, rp in placed if not looks_like_logo(rp, af)) > 1
        for box, area_frac, data, rep in placed:
            near = nearest_text(box, texts, ph_)
            opts = ([(t, "caption") for t in near[:2]] + [(title, "title")]) if multi else \
                ([(title, "title")] + [(t, "caption") for t in near[:3]])
            label, lsrc = choose_label(opts)
            own_lines = [t for t, bb in texts] if not multi else [t for t in near if t]
            qs, notes = parse_qa([t for t in own_lines if not same_label(t, label) and t != title])
            ctx = dict(base_ctx)
            ctx.update({
                "where": f"page {pno + 1}", "label": label, "label_src": lsrc,
                "hints": base_ctx["hints_pre"] + [(label or "", False), (title, False), (" ".join(near[:3]), False),
                                                  (section, False)] + base_ctx["hints_post"] + [(page_text, True)],
                "type_text": " ".join([label or "", title, " ".join(near[:4]), base_ctx["source"]]),
                "questions": qs, "notes": notes[:8], "repeat": rep, "area_frac": area_frac,
            })
            col.add(data, ctx)
    doc.close()


# ---- PPTX (read straight from the XML; no python-pptx needed)

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "p14": "http://schemas.microsoft.com/office/powerpoint/2010/main",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "v": "urn:schemas-microsoft-com:vml",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
R_EMBED = "{%s}embed" % NS["r"]
R_ID = "{%s}id" % NS["r"]


def read_rels(z, part):
    d, f = os.path.split(part)
    rp = f"{d}/_rels/{f}.rels"
    out = {}
    if rp not in z.namelist():
        return out
    root = ET.fromstring(z.read(rp))
    for rel in root.findall("rel:Relationship", NS):
        tgt = rel.get("Target", "")
        if rel.get("TargetMode") == "External":
            continue
        full = os.path.normpath(os.path.join(d, tgt)).replace("\\", "/") if not tgt.startswith("/") else tgt.lstrip("/")
        out[rel.get("Id")] = (full, rel.get("Type", ""))
    return out


def para_texts(el):
    out = []
    for p in el.iter("{%s}p" % NS["a"]):
        t = squash("".join(x.text or "" for x in p.iter("{%s}t" % NS["a"])))
        if t:
            out.append(t)
    return out


def xfrm_box(el):
    x = el.find(".//a:xfrm", NS)
    if x is None:
        return None
    off, ext = x.find("a:off", NS), x.find("a:ext", NS)
    if off is None or ext is None:
        return None
    X, Y, W, H = (int(off.get("x", 0)), int(off.get("y", 0)), int(ext.get("cx", 0)), int(ext.get("cy", 0)))
    return (X, Y, X + W, Y + H)


def process_pptx(col, path, base_ctx):
    try:
        z = zipfile.ZipFile(path)
    except Exception as e:
        col.errors.append(f"{base_ctx['source']}: not a valid PowerPoint file ({e})")
        return
    with z:
        names = set(z.namelist())
        if "ppt/presentation.xml" not in names:
            col.errors.append(f"{base_ctx['source']}: no slides found")
            return
        pres = ET.fromstring(z.read("ppt/presentation.xml"))
        prels = read_rels(z, "ppt/presentation.xml")
        sz = pres.find("p:sldSz", NS)
        sw, sh = (int(sz.get("cx")), int(sz.get("cy"))) if sz is not None else (9144000, 6858000)
        slides = []
        for s in pres.findall("p:sldIdLst/p:sldId", NS):
            rid = s.get(R_ID)
            if rid in prels:
                slides.append((s.get("id"), prels[rid][0]))
        section_of = {}
        for sec in pres.iter("{%s}section" % NS["p14"]):
            for sid in sec.iter("{%s}sldId" % NS["p14"]):
                section_of[sid.get("id")] = sec.get("name", "")
        # first pass: count on how many slides each media file appears (logos)
        parsed = []
        media_pages = {}
        for idx, (sid, part) in enumerate(slides):
            if part not in names:
                continue
            root = ET.fromstring(z.read(part))
            rels = read_rels(z, part)
            parsed.append((idx, sid, part, root, rels))
            for blip in root.iter("{%s}blip" % NS["a"]):
                rid = blip.get(R_EMBED)
                if rid in rels:
                    media_pages.setdefault(rels[rid][0], set()).add(idx)
        running = ""
        for idx, sid, part, root, rels in parsed:
            title, texts, pics, other = "", [], [], []
            layout_name = ""
            notes_lines = []
            for rid, (tgt, typ) in rels.items():
                if typ.endswith("/slideLayout") and tgt in names:
                    try:
                        lr = ET.fromstring(z.read(tgt))
                        c = lr.find("p:cSld", NS)
                        layout_name = (c.get("name", "") if c is not None else "") or ""
                    except Exception:
                        pass
                if typ.endswith("/notesSlide") and tgt in names:
                    try:
                        nr = ET.fromstring(z.read(tgt))
                        for sp in nr.iter("{%s}sp" % NS["p"]):
                            ph = sp.find(".//p:nvPr/p:ph", NS)
                            if ph is not None and ph.get("type") in ("sldNum", "sldImg", "hdr", "ftr", "dt"):
                                continue
                            notes_lines += para_texts(sp)
                    except Exception:
                        pass
            for el in root.iter():
                tag = el.tag.split("}")[-1]
                if tag in ("sp", "pic"):
                    blip = el.find(".//a:blip", NS)
                    if blip is not None and blip.get(R_EMBED) in rels:
                        pics.append((rels[blip.get(R_EMBED)][0], xfrm_box(el)))
                    if tag == "sp":
                        lines = para_texts(el)
                        if not lines:
                            continue
                        ph = el.find(".//p:nvPr/p:ph", NS)
                        ptype = ph.get("type") if ph is not None else None
                        if ptype in ("sldNum", "ftr", "dt", "hdr"):
                            continue
                        if ptype in ("title", "ctrTitle") and not title:
                            title = " ".join(lines)
                        else:
                            box = xfrm_box(el)
                            texts.append((" ".join(lines), box or (0, 0, sw, sh)))
                            other += lines
                elif tag == "graphicFrame":
                    other += para_texts(el)
            if not title and texts:
                top = sorted(texts, key=lambda t: t[1][1])[0]
                if top[1][1] < sh * 0.25 and len(top[0]) < 90:
                    title = top[0]
            sec = section_of.get(sid, "")
            if not pics and title and re.search(r"section|title", layout_name, re.I):
                running = title
            def _area(b):
                return ((b[2] - b[0]) * (b[3] - b[1]) / (sw * sh)) if b else None
            multi = sum(1 for m, b in pics if not looks_like_logo(len(media_pages.get(m, ())), _area(b))) > 1
            for media, box in pics:
                if media not in names:
                    continue
                ext = os.path.splitext(media)[1].lower()
                if ext in (".emf", ".wmf", ".svg", ".wdp"):
                    continue
                near = nearest_text(box, texts, sh) if box else [t for t, _ in texts]
                opts = ([(t, "caption") for t in near[:2]] + [(title, "title")]) if multi else \
                    ([(title, "title")] + [(t, "caption") for t in near[:3]])
                label, lsrc = choose_label(opts)
                own = (other if not multi else near[:3]) + notes_lines
                qs, notes = parse_qa([t for t in own if not same_label(t, label) and t != title])
                area = ((box[2] - box[0]) * (box[3] - box[1]) / (sw * sh)) if box else None
                ctx = dict(base_ctx)
                ctx.update({
                    "where": f"slide {idx + 1}", "label": label, "label_src": lsrc,
                    "hints": base_ctx["hints_pre"] + [(label or "", False), (title, False), (" ".join(near[:3]), False),
                                                      (sec, False), (running, False)] + base_ctx["hints_post"] +
                    [(" ".join(other + notes_lines), True)],
                    "type_text": " ".join([label or "", title, " ".join(near[:4]), " ".join(notes_lines[:4]), base_ctx["source"]]),
                    "questions": qs, "notes": notes[:8], "repeat": len(media_pages.get(media, ())), "area_frac": area,
                })
                try:
                    col.add(z.read(media), ctx)
                except KeyError:
                    pass


# ---- DOCX

def process_docx(col, path, base_ctx):
    try:
        z = zipfile.ZipFile(path)
    except Exception as e:
        col.errors.append(f"{base_ctx['source']}: not a valid Word file ({e})")
        return
    with z:
        if "word/document.xml" not in z.namelist():
            col.errors.append(f"{base_ctx['source']}: no document body")
            return
        root = ET.fromstring(z.read("word/document.xml"))
        rels = read_rels(z, "word/document.xml")
        W = "{%s}" % NS["w"]
        paras = []  # (text, style, [media])
        for p in root.iter(W + "p"):
            text = squash("".join(t.text or "" for t in p.iter(W + "t")))
            st = p.find(f"{W}pPr/{W}pStyle")
            style = st.get(W + "val", "") if st is not None else ""
            media = []
            for blip in p.iter("{%s}blip" % NS["a"]):
                rid = blip.get(R_EMBED)
                if rid in rels:
                    media.append(rels[rid][0])
            for im in p.iter("{%s}imagedata" % NS["v"]):
                rid = im.get(R_ID)
                if rid in rels:
                    media.append(rels[rid][0])
            paras.append((text, style, media))
        counts = {}
        for _, _, media in paras:
            for m in media:
                counts[m] = counts.get(m, 0) + 1
        headings = {}
        heading_text = ""
        for i, (text, style, media) in enumerate(paras):
            hm = re.match(r"(?:heading|titre|berschrift)\s*(\d)", style, re.I)
            if hm and text:
                lvl = int(hm.group(1))
                headings = {k: v for k, v in headings.items() if k < lvl}
                headings[lvl] = text
                heading_text = " / ".join(headings[k] for k in sorted(headings))
            elif style.lower() == "title" and text:
                headings = {0: text}
                heading_text = text
            if not media:
                continue
            after = [paras[j] for j in range(i + 1, min(len(paras), i + 8))]
            before = [paras[j] for j in range(max(0, i - 3), i)][::-1]
            # text after the picture up to the next picture/heading belongs to it
            block = []
            for t, s, m in after:
                if m or re.match(r"heading", s, re.I):
                    break
                if t:
                    block.append((t, s))
            caption_opts = []
            if text:
                caption_opts.append((text, "caption"))
            for t, s in block[:2]:
                caption_opts.append((t, "caption" if (s.lower() == "caption" or re.match(r"fig", t, re.I)) else "caption"))
            for t, s, m in before[:2]:
                if t and not m:
                    caption_opts.append((t, "caption"))
            if headings:
                caption_opts.append((headings[max(headings)], "heading"))
            label, lsrc = choose_label(caption_opts)
            qs, notes = parse_qa([t for t, _ in block if not same_label(t, label)])
            for m in media:
                if m not in z.namelist():
                    continue
                if os.path.splitext(m)[1].lower() in (".emf", ".wmf", ".svg"):
                    continue
                ctx = dict(base_ctx)
                ctx.update({
                    "where": f"near paragraph {i + 1}", "label": label, "label_src": lsrc,
                    "hints": base_ctx["hints_pre"] + [(label or "", False), (heading_text, False),
                                                      (" ".join(t for t, _ in block[:3]), False)] + base_ctx["hints_post"],
                    "type_text": " ".join([label or "", heading_text, " ".join(t for t, _ in block[:4]), base_ctx["source"]]),
                    "questions": qs, "notes": notes[:8], "repeat": counts.get(m, 1), "area_frac": None,
                })
                col.add(z.read(m), ctx)


# ---- loose images, zips, old office files

def process_image_file(col, path, base_ctx):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".heic", ".heif") and not HEIC_OK:
        col.errors.append(f"{base_ctx['source']}: .heic needs  pip install pillow-heif  — skipped")
        return
    try:
        im = Image.open(path)
        im.load()
    except Exception as e:
        col.errors.append(f"{base_ctx['source']}: could not read image ({e.__class__.__name__})")
        return
    label = label_from_filename(path)
    ctx = dict(base_ctx)
    ctx.update({
        "where": "", "label": label, "label_src": "filename" if label else "none",
        "hints": base_ctx["hints_pre"] + [(label or "", False)] + base_ctx["hints_post"],
        "type_text": " ".join([label or "", base_ctx["source"]]),
        "questions": [], "notes": [], "repeat": 1, "area_frac": None,
    })
    col.add(im, ctx)


def safe_extract_zip(path, dest):
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            name = info.filename
            try:  # zips made on Windows/phones often use cp437 names
                if not (info.flag_bits & 0x800):
                    name = name.encode("cp437").decode("utf-8")
            except Exception:
                pass
            target = os.path.normpath(os.path.join(dest, name))
            if not target.startswith(os.path.abspath(dest) + os.sep):
                continue  # path traversal attempt
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            if os.path.basename(target).startswith(("._", ".")) or "__MACOSX" in target:
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)


def convert_old_office(path, workdir, errors, source):
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    target = OLD_OFFICE[os.path.splitext(path)[1].lower()]
    if not soffice:
        errors.append(f"{source}: old format — open it and 'Save As' .{target} (or install LibreOffice)")
        return None
    out = tempfile.mkdtemp(dir=workdir)
    try:
        subprocess.run([soffice, "--headless", "--convert-to", target, "--outdir", out, path],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=240)
    except Exception as e:
        errors.append(f"{source}: conversion failed ({e})")
        return None
    for f in os.listdir(out):
        if f.lower().endswith("." + target):
            return os.path.join(out, f)
    errors.append(f"{source}: conversion failed")
    return None


def process_path(col, path, source, course, folder_hints, workdir, depth=0):
    ext = os.path.splitext(path)[1].lower()
    fname = os.path.splitext(os.path.basename(path))[0]
    base_ctx = {
        "course": course, "source": source,
        "hints_pre": [(h, False) for h in folder_hints],
        "hints_post": [(fname, False)],
    }
    if ext in OLD_OFFICE:
        conv = convert_old_office(path, workdir, col.errors, source)
        if conv:
            process_path(col, conv, source, course, folder_hints, workdir, depth)
        return
    print(f" • {source}")
    before = col.n
    try:
        if ext == ".pdf":
            process_pdf(col, path, base_ctx)
        elif ext in PPT_EXT:
            process_pptx(col, path, base_ctx)
        elif ext in DOC_EXT:
            process_docx(col, path, base_ctx)
        elif ext in IMAGE_EXT:
            process_image_file(col, path, base_ctx)
        elif ext == ".zip":
            if depth > 3:
                return
            dest = tempfile.mkdtemp(dir=workdir)
            try:
                safe_extract_zip(path, dest)
            except Exception as e:
                col.errors.append(f"{source}: bad zip ({e})")
                return
            for dp, dns, fns in os.walk(dest):
                dns.sort()
                for f in sorted(fns):
                    full = os.path.join(dp, f)
                    inner = os.path.relpath(full, dest)
                    sub = [p for p in os.path.dirname(inner).split(os.sep) if p]
                    process_path(col, full, f"{source} › {inner}", course, folder_hints + sub, workdir, depth + 1)
            return
        else:
            return
    except Exception as e:  # never let one bad file stop the run
        col.errors.append(f"{source}: failed ({e.__class__.__name__}: {e})")
    col.log(f"{col.n - before} image(s)")


# ----------------------------------------------------------------------------- bank / manifest

def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def rel(p):
    return os.path.relpath(p, ROOT).replace(os.sep, "/")


def abspath(r):
    return os.path.join(ROOT, *r.split("/"))


def bank_images():
    out = []
    if not os.path.isdir(BANK_DIR):
        return out
    for dp, dns, fns in os.walk(BANK_DIR):
        dns[:] = sorted(d for d in dns if not d.startswith("."))
        for f in sorted(fns):
            if os.path.splitext(f)[1].lower() in BANK_EXT and not f.startswith("."):
                out.append(os.path.join(dp, f))
    return out


def hash_bank(paths):
    cache = load_json(CACHE, {})
    out, new_cache = {}, {}
    for p in paths:
        r = rel(p)
        st = os.stat(p)
        key = f"{st.st_size}:{int(st.st_mtime)}"
        hit = cache.get(r)
        if hit and hit.get("key") == key and "v" in hit.get("h", {}):
            h = hit["h"]
        else:
            try:
                with Image.open(p) as im:
                    im = to_rgb(im)
                    h = image_hashes(im)
                    h["w"], h["h"] = im.size
            except Exception:
                continue
        new_cache[r] = {"key": key, "h": h}
        out[r] = h
    save_json(CACHE, new_cache)
    return out


def load_manifest():
    m = load_json(MANIFEST, {})
    m.setdefault("images", [])
    return m


def refresh_manifest(manifest, bank_hashes):
    """Follow images the user renamed/moved by hand (matched by picture hash); drop ones that were deleted."""
    by_path = {e["image"]: e for e in manifest["images"]}
    tracked = set(by_path)
    untracked = {r: h for r, h in bank_hashes.items() if r not in tracked}
    keep = []
    for e in manifest["images"]:
        if e["image"] in bank_hashes:
            keep.append(e)
            continue
        found = None
        for r, h in untracked.items():
            if format(h["ph"], "016x") == e["id"] or hamming(h["ph"], int(e["id"], 16)) <= 2:
                found = r
                break
        if found:
            untracked.pop(found)
            e["image"] = found
            side = load_json(abspath(sidecar_path(found)), {})
            if side.get("label") and side.get("image") in (None, os.path.basename(found)):
                e["label"] = side["label"]
            else:
                e["label"] = label_from_bank_name(found)
            parts = found.split("/")
            if len(parts) >= 4:
                e["course"], e["category"] = parts[1], parts[2]
            keep.append(e)
    manifest["images"] = keep
    return manifest


def label_from_bank_name(img_rel):
    """Same rule as build-bank.js: "wilms-tumour__2.jpg" -> "Wilms tumour"."""
    base = os.path.splitext(os.path.basename(img_rel))[0]
    if base.startswith("unlabelled"):
        return ""
    base = re.sub(r"__\d+$|\s*\(\d+\)$", "", base)
    base = squash(re.sub(r"[_-]+", " ", base))
    return base[:1].upper() + base[1:]


def sidecar_path(img_rel):
    return os.path.splitext(img_rel)[0] + ".json"


def unique_name(folder, slug, taken):
    name = slug
    i = 2
    while True:
        cand = os.path.join(folder, name + ".jpg")
        if rel(cand) not in taken and not any(os.path.exists(os.path.join(folder, name + e)) for e in BANK_EXT | {".json"}):
            return cand
        name = f"{slug}__{i}"
        i += 1


def next_unlabelled(folder, taken):
    i = 1
    while True:
        slug = f"unlabelled-{i:03d}"
        cand = os.path.join(folder, slug + ".jpg")
        if rel(cand) not in taken and not os.path.exists(cand):
            return cand
        i += 1


def save_bank_image(src_path, dest):
    with Image.open(src_path) as im:
        im = to_rgb(im)
        if max(im.size) > MAX_SIDE:
            im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        im.save(dest, quality=88, optimize=True)


# ----------------------------------------------------------------------------- grouping

def group_candidates(cands):
    n = len(cands)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        if n > 400 and i % 200 == 0:
            print(f"   comparing … {i}/{n}", end="\r", flush=True)
        a = cands[i]
        for j in range(i + 1, n):
            if is_duplicate(a, cands[j]):
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(cands[i])
    return list(groups.values())


LABEL_WEIGHT = {"caption": 3, "title": 3, "heading": 2, "filename": 1.5, "none": 0}


def merge_group(g):
    best = max(g, key=lambda c: (c["w"] * c["h"], c["bytes"]))
    # label: weighted vote across copies
    scores = {}
    for c in g:
        if c.get("label"):
            k = norm(c["label"])
            s = scores.setdefault(k, [0, c["label"]])
            s[0] += LABEL_WEIGHT.get(c.get("label_src"), 1) + 1
    label = max(scores.values(), key=lambda s: (s[0], -len(s[1])))[1] if scores else None
    if not label:  # no caption/title: use the answer to an "Identify ..." question if one was found
        for c in g:
            for q in c.get("questions", []):
                if q.get("a") and IDENTIFY_RE.match(q["q"]):
                    label = clean_label(q["a"]) or label
                    if label:
                        break
            if label:
                break
    course_votes = {}
    for c in g:
        course_votes[c["course"]] = course_votes.get(c["course"], 0) + 1
    course = max(course_votes.items(), key=lambda kv: kv[1])[0]
    cat_votes = {}
    for c in g:
        if c["course"] != course:
            continue
        hints = list(c["hints"])
        if label:
            hints.insert(len(c["hints_pre"]), (label, False))
        cat = pick_category(course, hints)
        if cat != "_Unsorted":
            cat_votes[cat] = cat_votes.get(cat, 0) + 1
    category = max(cat_votes.items(), key=lambda kv: kv[1])[0] if cat_votes else "_Unsorted"
    type_votes = {}
    for c in g:
        t = guess_type(course, (label or "") + " " + c.get("type_text", ""))
        if t:
            type_votes[t] = type_votes.get(t, 0) + 1
    typ = max(type_votes.items(), key=lambda kv: kv[1])[0] if type_votes else ""
    questions, seen_q = [], {}
    notes, seen_n = [], set()
    for c in g:
        for q in c.get("questions", []):
            # all "Identify this ..." variants count as one question
            kq = "identify" if IDENTIFY_RE.match(q["q"]) else norm(q["q"])
            if kq in seen_q:
                if q.get("a") and not questions[seen_q[kq]]["a"]:
                    questions[seen_q[kq]]["a"] = q["a"]
                continue
            seen_q[kq] = len(questions)
            questions.append({"q": q["q"], "a": q.get("a", "")})
        for nline in c.get("notes", []):
            k = norm(nline)
            if k and k not in seen_n and k != norm(label or ""):
                seen_n.add(k)
                notes.append(nline)
    sources = []
    for c in g:
        s = c["source"] + (f" ({c['where']})" if c.get("where") else "")
        if s not in sources:
            sources.append(s)
    return {"best": best, "label": label, "course": course, "category": category, "type": typ,
            "questions": questions[:10], "notes": notes[:12], "sources": sources, "copies": len(g),
            "id": format(best["ph"], "016x")}


# ----------------------------------------------------------------------------- outputs

def write_sidecar(img_rel, data):
    side = {}
    if data.get("type"):
        side["type"] = data["type"]
    side["label"] = data.get("label") or ""
    if data.get("questions"):
        side["questions"] = data["questions"]
    if data.get("notes"):
        side["notes"] = data["notes"]
    side["sources"] = data.get("sources", [])
    side["image"] = os.path.basename(img_rel)  # if you rename the picture, its new file name becomes the label
    save_json(abspath(sidecar_path(img_rel)), side)


def merge_into_existing(entry, data, bank_hash):
    """A new copy of a picture that extract.py already put in the bank: merge questions/notes, maybe upgrade pixels."""
    changed = []
    img_rel = entry["image"]
    side_p = abspath(sidecar_path(img_rel))
    side = load_json(side_p, {}) if os.path.exists(side_p) else {}
    qs = side.get("questions") or []
    have = {norm(q.get("q", "")) for q in qs if isinstance(q, dict)}
    added = [q for q in data["questions"] if norm(q["q"]) not in have]
    if added:
        side["questions"] = [q for q in qs if isinstance(q, dict) and (q.get("q") or "").strip()] + added
        changed.append(f"+{len(added)} question(s)")
    notes = side.get("notes") or []
    if isinstance(notes, str):
        notes = [notes]
    nn = {norm(x) for x in notes}
    extra = [x for x in data["notes"] if norm(x) not in nn]
    if extra:
        side["notes"] = (notes + extra)[:12]
    srcs = side.get("sources") or entry.get("sources") or []
    for s in data["sources"]:
        if s not in srcs:
            srcs.append(s)
    side["sources"] = srcs
    entry["sources"] = srcs
    entry["copies"] = entry.get("copies", 1) + data["copies"]
    best = data["best"]
    cur_px = (bank_hash.get("w", 0) or 0) * (bank_hash.get("h", 0) or 0)
    if best["w"] * best["h"] > cur_px * 1.2 and cur_px < MAX_SIDE * MAX_SIDE * 0.5:
        save_bank_image(best["path"], abspath(img_rel))
        changed.append("higher-resolution copy")
    if (not side.get("label")) and data.get("label") and os.path.basename(img_rel).startswith("unlabelled"):
        side["label"] = data["label"]
        changed.append("label found")
    if os.path.exists(side_p) or side:
        save_json(side_p, side)
    return changed


def write_corrections(manifest):
    with open(CORRECTIONS, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["id", "file", "course", "category", "label", "type", "delete"])
        for e in sorted(manifest["images"], key=lambda e: e["image"]):
            w.writerow([e["id"], e["image"], e["course"], e["category"], e.get("label", ""), e.get("type", ""), ""])


def write_report(manifest, rejects, errors, run_info):
    kept = []
    for e in sorted(manifest["images"], key=lambda e: (e["course"], e["category"], e["image"])):
        side = load_json(abspath(sidecar_path(e["image"])), {})
        kept.append({
            "id": e["id"], "file": e["image"], "src": "/".join(urllib.parse.quote(s) for s in e["image"].split("/")),
            "course": e["course"], "category": e["category"], "label": side.get("label", e.get("label", "")) or "",
            "type": side.get("type", e.get("type", "")) or "", "sources": e.get("sources", []), "copies": e.get("copies", 1),
            "questions": len([q for q in side.get("questions", []) if isinstance(q, dict) and q.get("q")]),
            "new": e.get("added") == run_info["date"],
        })
    cats = {}
    for c, lst in CATEGORIES.items():
        cats[c] = [n for n, _ in lst] + ["_Unsorted"]
    for k in kept:
        cats.setdefault(k["course"], [])
        if k["category"] not in cats[k["course"]]:
            cats[k["course"]].append(k["category"])
    data = {"kept": kept, "rejects": rejects, "errors": errors, "cats": cats, "run": run_info}
    page = REPORT_TEMPLATE.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(page)


def run_build_bank():
    node = shutil.which("node")
    if not node:
        print("\nNode.js not found — run  node build-bank.js  yourself after installing Node.")
        return
    print("\nRunning node build-bank.js …")
    subprocess.run([node, os.path.join(ROOT, "build-bank.js")], cwd=ROOT)


# ----------------------------------------------------------------------------- commands

def cmd_extract(args):
    if not os.path.isdir(SOURCE_DIR):
        os.makedirs(SOURCE_DIR, exist_ok=True)
        for c in COURSES:
            os.makedirs(os.path.join(SOURCE_DIR, c), exist_ok=True)
        print("Created /source with one folder per course. Put your PDFs, PowerPoints, Word files, zips and images there, then run again.")
        return
    if pymupdf is None:
        print("Note: PyMuPDF is not installed, so PDFs will be skipped.  pip install pymupdf")
    manifest = load_manifest()
    if args.fresh:
        n = 0
        for e in manifest["images"]:
            for p in (abspath(e["image"]), abspath(sidecar_path(e["image"]))):
                if os.path.exists(p):
                    os.makedirs(TRASH_DIR, exist_ok=True)
                    shutil.move(p, os.path.join(TRASH_DIR, os.path.basename(p)))
                    n += 1
        manifest["images"] = []
        print(f"--fresh: moved {n} previously extracted file(s) to extract-trash/")
        remove_empty_dirs(BANK_DIR)
    shutil.rmtree(REJECTS_DIR, ignore_errors=True)

    print("Hashing pictures already in /bank …")
    bank_hashes = hash_bank(bank_images())
    manifest = refresh_manifest(manifest, bank_hashes)
    tracked = {e["image"]: e for e in manifest["images"]}

    date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    work = tempfile.mkdtemp(prefix="pp-extract-")
    col = Collector(work, args.verbose)
    try:
        print("Reading /source …")
        for entry in sorted(os.listdir(SOURCE_DIR)):
            full = os.path.join(SOURCE_DIR, entry)
            if entry.startswith("."):
                continue
            if os.path.isdir(full):
                course = canonical_course(entry)
                for dp, dns, fns in os.walk(full):
                    dns[:] = sorted(d for d in dns if not d.startswith("."))
                    sub = [p for p in os.path.relpath(dp, full).split(os.sep) if p and p != "."]
                    for f in sorted(fns):
                        if f.startswith((".", "~$")):
                            continue
                        process_path(col, os.path.join(dp, f), rel(os.path.join(dp, f)).replace("source/", "", 1),
                                     course, list(reversed(sub)), work)
            else:
                col.errors.append(f"{entry}: put files inside a course folder (source/<Course>/), skipped")

        print(f"\nFound {col.n} pictures: {len(col.rejects)} junk, {len(col.cands)} to compare for duplicates …")
        groups = group_candidates(col.cands)
        stats = {"found": col.n, "junk": len(col.rejects), "groups": len(groups), "added": 0, "dups": 0,
                 "already": 0, "merged_existing": 0}

        taken = set(bank_hashes)
        for g in sorted(groups, key=lambda g: (g[0]["course"], g[0]["source"])):
            data = merge_group(g)
            best = data["best"]
            places = {(c["source"], c.get("where")) for c in g}
            labels = {norm(c["label"]) for c in g if c.get("label")}
            if len(places) >= 3 and len(labels) >= 2 and min(best["w"], best["h"]) < 700 and \
                    all(looks_like_logo(3, c.get("area_frac")) for c in g):
                for c in g:
                    with Image.open(c["path"]) as im:
                        col.reject(im.convert("RGB"), c, f"logo / crest (appears in {len(places)} places with different titles)")
                stats["junk"] += len(g)
                continue
            # duplicates inside this run
            for c in g:
                if c is not best:
                    stats["dups"] += 1
                    with Image.open(c["path"]) as im:
                        col.reject(im.convert("RGB"), c, "duplicate", dup_of=data["label"] or "(unlabelled)")
            # already in the bank?
            match = None
            for r, h in bank_hashes.items():
                if is_duplicate(best, h):
                    match = r
                    break
            if match:
                if match in tracked:
                    changes = merge_into_existing(tracked[match], data, bank_hashes[match])
                    stats["merged_existing"] += 1
                    why = "already in bank" + (": " + ", ".join(changes) if changes else "")
                else:
                    stats["already"] += 1
                    why = "already in bank (added by you)"
                with Image.open(best["path"]) as im:
                    col.reject(im.convert("RGB"), best, why, dup_of=match)
                continue
            folder = os.path.join(BANK_DIR, data["course"], data["category"])
            dest = unique_name(folder, slugify(data["label"]), taken) if data["label"] else next_unlabelled(folder, taken)
            save_bank_image(best["path"], dest)
            r = rel(dest)
            taken.add(r)
            bank_hashes[r] = {k: best[k] for k in ("ph", "v", "dh", "rgb")}
            bank_hashes[r].update({"w": best["w"], "h": best["h"]})
            write_sidecar(r, data)
            e = {"id": data["id"], "image": r, "course": data["course"], "category": data["category"],
                 "label": data["label"] or "", "type": data["type"], "sources": data["sources"],
                 "copies": data["copies"], "added": date}
            manifest["images"].append(e)
            tracked[r] = e
            stats["added"] += 1
    finally:
        shutil.rmtree(work, ignore_errors=True)

    manifest["updated"] = date
    manifest["last_run"] = {"date": date, "stats": stats, "rejects": col.rejects, "errors": col.errors}
    save_json(MANIFEST, manifest)
    hash_bank(bank_images())  # refresh cache
    write_corrections(manifest)
    run_info = {"date": date, "stats": stats}
    write_report(manifest, col.rejects, col.errors, run_info)

    print(f"\nDone. {stats['added']} new picture(s) added to /bank.")
    print(f"  {stats['dups']} duplicate copies merged, {stats['junk']} junk skipped, "
          f"{stats['already'] + stats['merged_existing']} already in the bank.")
    unsorted = sum(1 for e in manifest["images"] if e["category"] == "_Unsorted")
    unl = sum(1 for e in manifest["images"] if not e.get("label"))
    if unsorted or unl:
        print(f"  Check: {unsorted} in _Unsorted, {unl} unlabelled.")
    if col.errors:
        print(f"\n{len(col.errors)} problem(s):")
        for e in col.errors[:40]:
            print("  - " + e)
    print(f"\nOpen extract-report.html to check labels and categories.")
    print("Fix them there (Save corrections.csv) or edit corrections.csv, then run:  python3 extract.py --apply")
    if not args.no_build:
        run_build_bank()


def remove_empty_dirs(top):
    if not os.path.isdir(top):
        return
    for dp, dns, fns in os.walk(top, topdown=False):
        if dp != top and not os.listdir(dp):
            try:
                os.rmdir(dp)
            except OSError:
                pass


def cmd_apply(args):
    path = args.apply if isinstance(args.apply, str) else CORRECTIONS
    if not os.path.exists(path):
        sys.exit(f"{path} not found. Run python3 extract.py first.")
    manifest = load_manifest()
    bank_hashes = hash_bank(bank_images())
    manifest = refresh_manifest(manifest, bank_hashes)
    by_id = {e["id"]: e for e in manifest["images"]}
    by_file = {e["image"]: e for e in manifest["images"]}
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    moved = renamed = deleted = retyped = 0
    problems = []
    taken = set(bank_hashes)
    for row in rows:
        row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        e = by_id.get(row.get("id", "")) or by_file.get(row.get("file", ""))
        if not e:
            if row.get("file") and os.path.exists(abspath(row["file"])):
                h = bank_hashes.get(row["file"])
                e = {"id": format(h["ph"], "016x") if h else row.get("id", ""), "image": row["file"],
                     "course": row["file"].split("/")[1], "category": row["file"].split("/")[2] if row["file"].count("/") >= 3 else "",
                     "label": "", "type": "", "sources": [], "copies": 1}
                manifest["images"].append(e)
            else:
                problems.append(f"row for {row.get('file') or row.get('id')}: picture not found")
                continue
        img = abspath(e["image"])
        side_p = abspath(sidecar_path(e["image"]))
        if row.get("delete", "").lower() in ("y", "yes", "1", "x", "true", "delete"):
            os.makedirs(TRASH_DIR, exist_ok=True)
            for p in (img, side_p):
                if os.path.exists(p):
                    shutil.move(p, os.path.join(TRASH_DIR, os.path.basename(p)))
            manifest["images"].remove(e)
            deleted += 1
            continue
        side = load_json(side_p, {}) if os.path.exists(side_p) else {}
        course = row.get("course") or e["course"]
        category = row.get("category") or e["category"] or "_Unsorted"
        label = row.get("label", "")
        typ = row.get("type", "").lower()
        if typ and typ not in ("slide", "pot", "photomicrograph"):
            problems.append(f"{e['image']}: type '{typ}' is not slide / pot / photomicrograph — ignored")
            typ = side.get("type", "")
        old_label = side.get("label", "") or e.get("label", "")
        folder = os.path.join(BANK_DIR, course, category)
        cur_base = os.path.splitext(os.path.basename(img))[0]
        want_slug = slugify(label) if label else (cur_base if cur_base.startswith("unlabelled") else None)
        new_img = img
        same_folder = os.path.normcase(os.path.dirname(img)) == os.path.normcase(folder)
        slug_ok = want_slug is not None and re.sub(r"__\d+$", "", cur_base) == want_slug
        if not same_folder or not slug_ok:
            taken.discard(e["image"])
            new_img = unique_name(folder, want_slug, taken) if label else (
                os.path.join(folder, os.path.basename(img)) if cur_base.startswith("unlabelled") and not os.path.exists(os.path.join(folder, os.path.basename(img)))
                else next_unlabelled(folder, taken))
            os.makedirs(folder, exist_ok=True)
            shutil.move(img, new_img)
            if os.path.exists(side_p):
                shutil.move(side_p, os.path.splitext(new_img)[0] + ".json")
            if not same_folder:
                moved += 1
            if not slug_ok:
                renamed += 1
        r = rel(new_img)
        taken.add(r)
        if side.get("image") and side["image"] != os.path.basename(r):
            side["image"] = os.path.basename(r)
            save_json(abspath(sidecar_path(r)), side)
        if label != old_label or typ != side.get("type", ""):
            if typ != side.get("type", ""):
                retyped += 1
            side["label"] = label
            side["image"] = os.path.basename(r)
            if typ:
                side["type"] = typ
            else:
                side.pop("type", None)
            save_json(abspath(sidecar_path(r)), side)
        e.update({"image": r, "course": course, "category": category, "label": label, "type": typ})
    remove_empty_dirs(BANK_DIR)
    save_json(MANIFEST, manifest)
    hash_bank(bank_images())
    write_corrections(manifest)
    last = manifest.get("last_run") or {}
    write_report(manifest, last.get("rejects", []), last.get("errors", []),
                 {"date": last.get("date", manifest.get("updated", "")), "stats": last.get("stats")})
    print(f"Applied corrections: {moved} moved, {renamed} renamed, {retyped} type changes, {deleted} deleted (in extract-trash/).")
    for p in problems:
        print("  - " + p)
    if not args.no_build:
        run_build_bank()


def main():
    ap = argparse.ArgumentParser(description="Extract pictures from /source into /bank (see README.md).")
    ap.add_argument("--apply", nargs="?", const=True, metavar="CSV", help="apply corrections.csv (or the CSV you name)")
    ap.add_argument("--fresh", action="store_true", help="remove everything extract.py added before, then extract again")
    ap.add_argument("--no-build", action="store_true", help="do not run node build-bank.js at the end")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    if args.apply:
        cmd_apply(args)
    else:
        cmd_extract(args)


# ----------------------------------------------------------------------------- report page

REPORT_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Extract Report</title>
<style>
:root{--bg:#f4f5f7;--card:#fff;--ink:#1b2330;--muted:#5d6879;--line:#dde1e7;--accent:#2c5282;--bad:#c0392b;--warn:#b7791f}
[hidden]{display:none!important}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--ink)}
header{position:sticky;top:0;z-index:5;background:#fff;border-bottom:1px solid var(--line);padding:10px 16px}
h1{margin:0;font-size:1.3rem}h2{margin:24px 16px 8px;font-size:1.1rem}
.stats{color:var(--muted);font-size:.9rem;margin:4px 0 8px}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.bar input[type=search],.bar select{padding:8px 10px;border:1px solid var(--line);border-radius:8px;font:inherit;min-height:40px}
.bar label{font-size:.9rem;display:flex;gap:6px;align-items:center}
button{font:inherit;padding:8px 14px;border-radius:8px;border:1px solid var(--line);background:#fff;cursor:pointer;min-height:40px}
.primary{background:var(--accent);color:#fff;border-color:var(--accent);font-weight:600}
.help{background:#eaf1fb;border:1px solid #c6d8f0;border-radius:10px;padding:10px 14px;margin:12px 16px;font-size:.92rem}
.help code{background:#fff;padding:1px 5px;border-radius:4px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px;padding:0 16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;display:flex;flex-direction:column}
.card.changed{border:2px solid var(--warn)}.card.del{opacity:.45}
.card img{width:100%;height:180px;object-fit:contain;background:#111;cursor:zoom-in}
.card .body{padding:8px 10px 10px;display:flex;flex-direction:column;gap:6px;font-size:.88rem}
.card input,.card select{width:100%;padding:6px 8px;border:1px solid var(--line);border-radius:6px;font:inherit}
.card .lbl{font-weight:600}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.meta{color:var(--muted);font-size:.8rem;word-break:break-word}
.badge{display:inline-block;background:#eef0f3;border-radius:999px;padding:1px 8px;font-size:.75rem;margin-right:4px}
.badge.warn{background:#fdf1dc;color:var(--warn)}.badge.new{background:#e3f5ea;color:#1f8a4c}
.rej{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px;padding:0 16px 40px}
.rej div{background:#fff;border:1px solid var(--line);border-radius:8px;padding:6px;font-size:.78rem}
.rej img{width:100%;height:110px;object-fit:contain;background:#111;border-radius:4px}
.rej b{color:var(--bad)}
.errs{margin:0 16px;font-size:.88rem;color:var(--bad)}
.lightbox{position:fixed;inset:0;background:rgba(0,0,0,.9);display:flex;align-items:center;justify-content:center;z-index:9}
.lightbox img{max-width:95vw;max-height:95vh}
</style></head><body>
<header>
  <h1>Extract report</h1>
  <div class="stats" id="stats"></div>
  <div class="bar">
    <input type="search" id="q" placeholder="Search label / file / source">
    <select id="fcourse"><option value="">All courses</option></select>
    <label><input type="checkbox" id="fneeds"> Only unsorted / unlabelled</label>
    <label><input type="checkbox" id="fnew"> Only new this run</label>
    <button class="primary" id="save">Save corrections.csv</button>
    <span id="changes" class="stats"></span>
  </div>
</header>
<div class="help">Fix any wrong <b>label</b>, <b>category</b> or <b>type</b> below (or tick <b>delete</b>). Then click
<b>Save corrections.csv</b>, save it in the Practical Projector folder (replace the old one) and run
<code>python3 extract.py --apply</code>. That moves and renames the files and rebuilds the bank.
You can also edit <code>corrections.csv</code> in Excel / Google Sheets instead.</div>
<h2 id="kept-title">Kept pictures</h2>
<div class="grid" id="grid"></div>
<h2 id="rej-title">Rejected this run (duplicates and junk)</h2>
<div class="rej" id="rej"></div>
<h2 id="err-title">Problems</h2><ul class="errs" id="errs"></ul>
<div class="lightbox" id="lb" hidden><img alt="" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"></div>
<script>
const DATA = /*DATA*/null;
const edits = {};
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const st = DATA.run.stats;
$('#stats').textContent = `${DATA.kept.length} pictures in the bank from extract.py` + (st ? ` · this run (${DATA.run.date}): ${st.found} found, ${st.added} added, ${st.dups} duplicate copies merged, ${st.junk} junk skipped, ${st.already + st.merged_existing} already in bank` : '');
const courses = [...new Set(DATA.kept.map((k) => k.course))];
$('#fcourse').innerHTML += courses.map((c) => `<option>${esc(c)}</option>`).join('');
function val(k, f) { return edits[k.id] && f in edits[k.id] ? edits[k.id][f] : k[f]; }
function render() {
  const q = $('#q').value.toLowerCase(), fc = $('#fcourse').value, needs = $('#fneeds').checked, onlyNew = $('#fnew').checked;
  const list = DATA.kept.filter((k) => (!fc || k.course === fc) && (!needs || !val(k, 'label') || val(k, 'category') === '_Unsorted') &&
    (!onlyNew || k.new) && (!q || (val(k, 'label') + ' ' + k.file + ' ' + k.sources.join(' ')).toLowerCase().includes(q)));
  $('#kept-title').textContent = `Kept pictures (${list.length})`;
  $('#grid').innerHTML = list.map((k) => {
    const cats = (DATA.cats[val(k, 'course')] || DATA.cats[k.course] || []).map((c) => `<option ${c === val(k, 'category') ? 'selected' : ''}>${esc(c)}</option>`).join('');
    const changed = edits[k.id] && Object.keys(edits[k.id]).length;
    return `<div class="card ${changed ? 'changed' : ''} ${val(k, 'delete') ? 'del' : ''}" data-id="${k.id}">
      <img loading="lazy" src="${esc(k.src)}" alt="">
      <div class="body">
        <input class="lbl" data-f="label" value="${esc(val(k, 'label'))}" placeholder="(unlabelled — type a label)">
        <div class="row2">
          <select data-f="course">${Object.keys(DATA.cats).map((c) => `<option ${c === val(k, 'course') ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select>
          <select data-f="category">${cats}<option value="__new">+ New category…</option></select>
        </div>
        <div class="row2">
          <select data-f="type">${['', 'slide', 'pot', 'photomicrograph'].map((t) => `<option value="${t}" ${t === val(k, 'type') ? 'selected' : ''}>${t || '(type unknown)'}</option>`).join('')}</select>
          <label style="display:flex;gap:6px;align-items:center"><input type="checkbox" data-f="delete" ${val(k, 'delete') ? 'checked' : ''} style="width:auto"> delete</label>
        </div>
        <div>${k.new ? '<span class="badge new">new</span>' : ''}${k.copies > 1 ? `<span class="badge">${k.copies - 1} duplicate${k.copies > 2 ? 's' : ''} merged</span>` : ''}${k.questions ? `<span class="badge">${k.questions} question${k.questions > 1 ? 's' : ''}</span>` : ''}${val(k, 'category') === '_Unsorted' ? '<span class="badge warn">unsorted</span>' : ''}${!val(k, 'label') ? '<span class="badge warn">unlabelled</span>' : ''}</div>
        <div class="meta">${esc(k.file)}</div>
        <div class="meta">From: ${k.sources.map(esc).join('; ')}</div>
      </div></div>`;
  }).join('');
  const n = Object.values(edits).filter((e) => Object.keys(e).length).length;
  $('#changes').textContent = n ? `${n} unsaved change${n > 1 ? 's' : ''}` : '';
}
$('#grid').addEventListener('change', (e) => {
  const card = e.target.closest('.card'); if (!card) return;
  const k = DATA.kept.find((x) => x.id === card.dataset.id);
  const f = e.target.dataset.f;
  let v = e.target.type === 'checkbox' ? e.target.checked : e.target.value.trim();
  if (f === 'category' && v === '__new') { v = (prompt('New category name (becomes a folder):') || '').trim(); if (!v) { render(); return; } (DATA.cats[val(k, 'course')] = DATA.cats[val(k, 'course')] || []).push(v); }
  if (f === 'course') { DATA.cats[v] = DATA.cats[v] || ['_Unsorted']; }
  edits[k.id] = edits[k.id] || {};
  if (v === k[f] || (f === 'delete' && !v)) delete edits[k.id][f]; else edits[k.id][f] = v;
  if (f === 'course' && !(DATA.cats[v] || []).includes(val(k, 'category'))) edits[k.id].category = '_Unsorted';
  render();
});
$('#grid').addEventListener('click', (e) => { if (e.target.tagName === 'IMG') { $('#lb img').src = e.target.src; $('#lb').hidden = false; } });
$('#lb').addEventListener('click', () => { $('#lb').hidden = true; });
['#q', '#fcourse', '#fneeds', '#fnew'].forEach((s) => $(s).addEventListener('input', render));
function csvCell(s) { s = String(s == null ? '' : s); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; }
$('#save').addEventListener('click', async () => {
  const rows = [['id', 'file', 'course', 'category', 'label', 'type', 'delete']];
  for (const k of DATA.kept) rows.push([k.id, k.file, val(k, 'course'), val(k, 'category'), val(k, 'label'), val(k, 'type'), val(k, 'delete') ? 'yes' : '']);
  const text = '﻿' + rows.map((r) => r.map(csvCell).join(',')).join('\r\n') + '\r\n';
  const blob = new Blob([text], { type: 'text/csv' });
  try {
    if (window.showSaveFilePicker) {
      const h = await window.showSaveFilePicker({ suggestedName: 'corrections.csv', types: [{ description: 'CSV', accept: { 'text/csv': ['.csv'] } }] });
      const w = await h.createWritable(); await w.write(blob); await w.close();
      alert('Saved. Now run:  python3 extract.py --apply'); return;
    }
  } catch (e) { if (e && e.name === 'AbortError') return; }
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'corrections.csv'; a.click();
  setTimeout(() => alert('Downloaded corrections.csv. Move it into the Practical Projector folder (replace the old one), then run:  python3 extract.py --apply'), 300);
});
$('#rej-title').textContent = `Rejected this run (${DATA.rejects.length})`;
$('#rej').innerHTML = DATA.rejects.length ? DATA.rejects.map((r) => `<div>${r.thumb ? `<img loading="lazy" src="extract-rejects/${esc(r.thumb)}" alt="">` : ''}
  <b>${esc(r.reason)}</b>${r.dup_of ? `<br>of: ${esc(r.dup_of)}` : ''}${r.label ? `<br>label: ${esc(r.label)}` : ''}<br><span class="meta">${esc(r.source)} ${esc(r.where)}</span></div>`).join('')
  : '<p class="meta">Nothing was rejected in the last run.</p>';
$('#err-title').hidden = !DATA.errors.length;
$('#errs').innerHTML = DATA.errors.map((e) => `<li>${esc(e)}</li>`).join('');
render();
</script></body></html>
"""

if __name__ == "__main__":
    main()
