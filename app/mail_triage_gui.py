#!/usr/bin/python3
"""Trencher: a desktop window for adjudicating a bay of email.

The 21 numbered folders are a triage station, not a filing cabinet. Mail arrives,
the filters and the sorter put each message in a bay, and the reader walks the bay
and makes one of three decisions about each message:

    stay      it is correctly placed and can wait there
    relocate  it is correctly placed but can go to its permanent folder now
    misfiled  it belongs in a different bay, and the sorter should be told why

The third decision is the only one that changes the machine: it writes a rule into
~/.hermes/config/mail_triage.json and regenerates the Betterbird filters, so the
same sender is not misjudged again.

No record of review is kept. The only state this program holds is how far through
each bay the reader has got, so that quitting and returning resumes rather than
starting again — and a button to forget even that.

    python3 mail_triage_gui.py
"""
import email
import email.header
import email.policy
import email.utils
import json
import os
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
TRENCHER = os.path.dirname(HERE)                  # ~/Trencher
SCRIPTS = os.path.expanduser("~/.hermes/scripts")  # shared mail library and cron
sys.path.insert(0, SCRIPTS)
import mail_move as mm            # noqa: E402  (profile, account, running, mbox reader)

# The rule table stays under ~/.hermes/config: mail_rules.py, which five cron
# jobs run, generates the Betterbird filters from it. Everything belonging to
# this program alone lives under ~/Trencher.
CONFIG = os.path.expanduser("~/.hermes/config/mail_triage.json")
MENU = os.path.join(TRENCHER, "config", "mail_triage_menu.json")
STATE = os.path.join(TRENCHER, "state", "trencher.json")
LAST = os.path.join(TRENCHER, "state", "last_destination.json")
BACKUPS = os.path.join(TRENCHER, "backups")
ICON_DIR = os.path.join(TRENCHER, "images")
BANNER = os.path.join(ICON_DIR, "banner.png")
ICON = os.path.join(ICON_DIR, "Trencher.png")
RULES_SCRIPT = os.path.join(SCRIPTS, "mail_rules.py")

# ── the palette, taken from the mark itself ──────────────────────────────────
# background.png — the pale blue of the field
BG = "#6dadf8"
# foreground.png — the deep blue of the cap, figure and lettering
INK = "#051bf8"
# the cards and panels that carry the text stay white, so the ink stays legible
CARD = "#ffffff"
CARD_EDGE = "#c9d8fb"
CARD_TINT = "#dbe6fd"

SKIP_FILES = (".msf", ".dat", ".json", ".html", ".sqlite")
ADDR_RE = re.compile(r"[\w.+-]+@[\w.-]+")


# ── the store ────────────────────────────────────────────────────────────────

class Folder:
    def __init__(self, label, path, account, is_bay, parts=()):
        self.label, self.path, self.account, self.is_bay = label, path, account, is_bay
        self.parts = tuple(parts)          # path within the account, e.g. ('family', 'Alice')
        self.key = " / ".join(self.parts)  # how the menu mapping names it

    def __repr__(self):
        return f"<Folder {self.label!r}>"


def load_folders():
    """Every mbox folder in the profile, at any depth, bays identified.

    A folder may be both an mbox file and a ``.sbd`` directory of sub-folders
    (``family`` holds its own mail and contains ``Alice``), so the walk takes the
    file and then descends. Reading a single level here meant the sub-sub folders
    — family / Alice / vio — could never be reached from the menu.
    """
    cfg = json.load(open(CONFIG, encoding="utf-8"))
    bay_account, bay_parent = cfg.get("account"), cfg["parent"]
    root = os.path.join(mm.profile(), "Mail")
    out = []

    def walk(directory, account, parts):
        names, subdirs = set(), {}
        for entry in sorted(os.listdir(directory)):
            path = os.path.join(directory, entry)
            if os.path.isfile(path):
                if not entry.endswith(SKIP_FILES):
                    names.add(entry)
            elif os.path.isdir(path) and entry.endswith(".sbd"):
                stem = entry[:-4]
                names.add(stem)
                subdirs[stem] = path
        for name in sorted(names, key=str.lower):
            here = parts + [name]
            path = os.path.join(directory, name)
            is_bay = (account == bay_account and len(here) == 2 and here[0] == bay_parent)
            if os.path.isfile(path):
                if is_bay:
                    label = name
                else:
                    label = " / ".join(here)
                    if account != bay_account:
                        label = f"{account} · {label}"
                out.append(Folder(label, path, account, is_bay, here))
            if name in subdirs:
                walk(subdirs[name], account, here)

    for account in sorted(os.listdir(root)):
        base = os.path.join(root, account)
        if not os.path.isdir(base) or account.endswith(".sbd"):
            continue
        walk(base, account, [])
    return out


def read_headers(raw):
    """From/To/Date/Subject/Message-ID by regex: a full email parse is too slow
    over a folder of a thousand messages just to draw a list."""
    head = raw.split(b"\n\n", 1)[0]
    fields = {}
    for name in (b"From", b"To", b"Date", b"Subject", b"Message-ID"):
        match = re.search(rb"(?mi)^" + name + rb":[ \t]*(.*(?:\n[ \t].*)*)", head)
        if match:
            fields[name.decode().lower()] = match.group(1)
    mid = (fields.get("message-id", b"") or b"").strip().strip(b"<>").decode("utf-8", "replace")
    return {
        "id": mid.lower(),
        "from": decode_header(fields.get("from", b"")),
        "to": decode_header(fields.get("to", b"")),
        "date": decode_header(fields.get("date", b"")),
        "subject": decode_header(fields.get("subject", b"")) or "(no subject)",
    }


def decode_header(value):
    if isinstance(value, bytes):
        text = value.decode("utf-8", "replace")
    else:
        text = str(value)
    text = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
    try:
        return str(email.header.make_header(email.header.decode_header(text)))
    except Exception:
        return text


def sender_address(from_field):
    match = ADDR_RE.search(from_field or "")
    return match.group(0).lower() if match else ""


def sender_domain(from_field):
    address = sender_address(from_field)
    return address.split("@")[-1] if "@" in address else ""


def parse_ts(text):
    try:
        return email.utils.parsedate_to_datetime(text).timestamp()
    except (TypeError, ValueError):
        return 0.0


def nice_date(text):
    """Brisbane-local, human: 'Sun 4 Oct 2026, 1:44 pm'."""
    try:
        moment = email.utils.parsedate_to_datetime(text).astimezone()
        hour = moment.strftime("%I").lstrip("0") or "12"
        return f"{moment.strftime('%a %-d %b %Y')}, {hour}:{moment.strftime('%M %p').lower()}"
    except (TypeError, ValueError):
        return text


def scan(path, with_offsets=False):
    """Header lines of every message in a folder, in file order."""
    out, offset, start = [], 0, None
    head = bytearray()
    with open(path, "rb") as fh:
        for line in fh:
            if line.startswith(b"From "):
                if start is not None:
                    entry = read_headers(bytes(head))
                    entry["ts"] = parse_ts(entry["date"])
                    entry["when"] = nice_date(entry["date"])
                    out.append({**entry, "offset": start})
                start, head = offset, bytearray()
            if start is not None and len(head) < 20000:
                head.extend(line)
            offset += len(line)
        if start is not None:
            entry = read_headers(bytes(head))
            entry["ts"] = parse_ts(entry["date"])
            entry["when"] = nice_date(entry["date"])
            out.append({**entry, "offset": start})
    return out


def read_at(path, offset):
    with open(path, "rb") as fh:
        fh.seek(offset)
        chunks = []
        for line in fh:
            if chunks and line.startswith(b"From "):
                break
            chunks.append(line)
    raw = b"".join(chunks)
    try:
        return email.message_from_bytes(raw, policy=email.policy.default)
    except Exception:
        return None


def body_text(msg):
    """A readable plain-text rendering, quoted text included."""
    if msg is None:
        return "(this message could not be read)"
    parts = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get_content_type() == "text/plain":
                parts.append(decode_part(part))
            elif part.get_content_type() == "text/html" and not parts:
                parts.append(strip_html(decode_part(part)))
    else:
        text = decode_part(msg)
        parts.append(strip_html(text) if msg.get_content_type() == "text/html" else text)
    parts = [strip_html(p) if looks_html(p) else p for p in parts]
    body = "\n\n".join(p.strip() for p in parts if p and p.strip())
    # Tk draws stray control characters as boxes; CRLF is the usual offender
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    body = re.sub(r"\n{3,}", "\n\n", body)
    body = "".join(ch for ch in body if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    return body or "(no readable text in this message)"


def decode_part(part):
    try:
        return part.get_content()
    except Exception:
        payload = part.get_payload(decode=True) or b""
        return payload.decode(part.get_content_charset() or "utf-8", "replace")


def looks_html(text):
    """Some senders put an HTML document inside a text/plain part; show the words."""
    head = (text or "").lstrip()[:400].lower()
    return head.startswith("<!doctype") or head.startswith("<html") or "<body" in head


def strip_html(html):
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    for entity, char in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"),
                         ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")):
        text = text.replace(entity, char)
    return re.sub(r"[ \t]{2,}", " ", text)


def move_message(src_path, dest_path, msg_id):
    """Move one message, holding the store lock so no cron sweep rewrites under us."""
    with mm.move_lock(blocking=True) as got:
        if not got:
            return False
        return _move_locked(src_path, dest_path, msg_id)


def _move_locked(src_path, dest_path, msg_id):
    # defence in depth: the window checks this too, but the store must never be
    # rewritten underneath a running client, whoever calls this
    if mm.running():
        return False
    keep = mm.temp_path(src_path)
    taken = None
    with open(keep, "wb") as out:
        for raw in mm.iter_blocks(src_path):
            mid, digest = mm.identity(raw)
            if taken is None and (mid or digest or "").lower() == msg_id:
                taken = raw
            else:
                out.write(raw)
    if taken is None:
        os.unlink(keep)
        return False
    stamp = time.strftime("%Y%m%d-%H%M%S")
    folder = os.path.join(BACKUPS, stamp)
    os.makedirs(folder, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(src_path))
    with open(os.path.join(folder, f"{safe}.mbox"), "ab") as fh:
        fh.write(taken if taken.endswith(b"\n") else taken + b"\n")
    os.replace(keep, src_path)
    for msf in (src_path + ".msf", dest_path + ".msf"):
        if os.path.exists(msf):
            os.unlink(msf)
    with open(dest_path, "ab") as fh:
        if not taken.startswith(b"From "):
            fh.write(b"From MAILER-DAEMON Thu Jan  1 00:00:00 1970\n")
        fh.write(taken if taken.endswith(b"\n") else taken + b"\n")
    # a rewrite leaves every stored byte offset pointing into the wrong place
    try:
        root = mm.account_dir() + os.sep

        def label_of(path):
            if not path.startswith(root):
                return None
            rel = os.path.relpath(path, root)
            return rel.replace("Incoming mail.sbd" + os.sep, "Incoming mail/")

        src_label, dest_label = label_of(src_path), label_of(dest_path)
        labels = [x for x in (src_label, dest_label) if x]
        if labels:
            mm.rebaseline(labels, rewritten={src_label} if src_label else ())
    except Exception:
        pass
    return True


# ── rules ────────────────────────────────────────────────────────────────────

def load_cfg():
    return json.load(open(CONFIG, encoding="utf-8"))


def save_cfg(cfg):
    tmp = CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG)


def category(cfg, folder_name):
    for cat in cfg["categories"]:
        if cat["folder"] == folder_name:
            return cat
    return None


def add_rule(cfg, folder_name, scope, value):
    """Write one rule. Returns (changed, message)."""
    cat = category(cfg, folder_name)
    if cat is None:
        return False, f"no such category: {folder_name}"
    value = (value or "").strip()
    if not value:
        return False, "the rule needs a value"
    if scope == "address":
        bucket = cat.setdefault("addresses", [])
        if value.lower() in (a.lower() for a in bucket):
            return False, "that address already has this rule"
        bucket.append(value.lower())
        return True, f"Every message from {value} → {folder_name} (address rule)."
    if scope == "domain":
        bucket = cat.setdefault("domains", [])
        if value.lower() in (d.lower() for d in bucket):
            return False, "that domain already has this rule"
        bucket.append(value.lower())
        return True, f"Every message from @{value} → {folder_name} (domain rule)."
    field = {"subject": "subject", "body": "body"}.get(scope)
    if not field:
        return False, f"unknown scope {scope!r}"
    label = f"{folder_name} — {field} contains “{value}”"
    for old in cfg.setdefault("extra_rules", []):
        if old.get("name") == label:
            return False, "that rule already exists"
    cfg["extra_rules"].append({
        "name": label,
        "path": [cfg["parent"], folder_name],
        "condition": f"({field},contains,{value})",
    })
    return True, f"Any message with “{value}” in the {field} → {folder_name} (content rule)."


def regenerate_filters():
    result = subprocess.run([sys.executable, RULES_SCRIPT],
                            capture_output=True, text=True)
    text = ((result.stdout or "") + (result.stderr or "")).strip()
    return result.returncode == 0, (text.splitlines()[0] if text else "")


def rule_matches(folders, scope, value, target):
    """What a candidate rule would claim, before it is saved."""
    needle = (value or "").strip().lower()
    if not needle:
        return {}, 0
    per_folder, total = {}, 0
    for folder in folders:
        if not (folder.is_bay or folder.label == "Inbox"):
            continue
        count = 0
        for header in scan(folder.path):
            if scope == "address":
                hit = sender_address(header["from"]) == needle
            elif scope == "domain":
                host = sender_domain(header["from"])
                hit = host == needle or host.endswith("." + needle)
            elif scope == "subject":
                hit = needle in header["subject"].lower()
            else:
                hit = needle in header["subject"].lower()   # body checked below
            if scope == "body":
                hit = needle.encode() in read_raw(folder.path, header["offset"]).lower()
            if hit:
                count += 1
                if folder.label != target:
                    pass
        if count:
            per_folder[folder.label] = count
            total += count
    return per_folder, total


def read_raw(path, offset):
    with open(path, "rb") as fh:
        fh.seek(offset)
        chunks = []
        for line in fh:
            if chunks and line.startswith(b"From "):
                break
            chunks.append(line)
    return b"".join(chunks)


# ── the window ───────────────────────────────────────────────────────────────

def bay_order(folder):
    match = re.match(r"\s*(\d+)", folder.label)
    return (int(match.group(1)) if match else 999, folder.label)


class Triage(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Trencher")
        try:
            self.iconphoto(True, tk.PhotoImage(file=ICON))
        except tk.TclError:
            pass
        self.geometry("1200x800")
        self.minsize(960, 640)
        self.configure(bg=BG)
        self.folders = load_folders()
        self.bays = sorted([f for f in self.folders if f.is_bay], key=bay_order)
        self.state = self.load_state()
        self.current = None
        self.queue = []
        self.shown = None
        self.icons = self.load_icons()
        self.build()
        self.warn_if_running()
        self.after(15000, self.watch_app)
        threading.Thread(target=self.fill_counts, daemon=True).start()
        self.focus_set()
        # a testing hook: open straight onto a bay (and its misfiled panel) so the
        # window can be photographed without a human at the mouse
        demo = os.environ.get("TRIAGE_DEMO_BAY")
        if demo:
            self.after(600, lambda: self.select_bay(demo))
            if os.environ.get("TRIAGE_DEMO_DIALOG"):
                self.after(2600, self.do_misfiled)
            if os.environ.get("TRIAGE_DEMO_PICKER"):
                self.after(2600, self.do_relocate)

    def select_bay(self, label):
        if self.tree.exists(label):
            self.tree.selection_set(label)
            self.tree.see(label)

    def load_state(self):
        try:
            return json.load(open(STATE, encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save_state(self):
        try:
            os.makedirs(os.path.dirname(STATE), exist_ok=True)
            with open(STATE, "w", encoding="utf-8") as fh:
                json.dump(self.state, fh)
        except OSError:
            pass

    def load_icons(self):
        icons = {}
        for name in ("stay", "relocate", "alert", "newfolder", "trash"):
            path = os.path.join(ICON_DIR, f"{name}.png")
            if os.path.exists(path):
                try:
                    icons[name] = tk.PhotoImage(file=path)
                except tk.TclError:
                    pass
        return icons

    def build(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=INK)
        style.configure("Treeview", rowheight=26, font=("DejaVu Sans", 11),
                        background=CARD, fieldbackground=CARD,
                        foreground=INK)
        style.map("Treeview",
                  background=[("selected", CARD_TINT)],
                  foreground=[("selected", INK)])
        style.configure("Treeview.Heading", font=("DejaVu Sans", 10, "bold"))
        style.configure("Subject.TLabel", font=("DejaVu Sans", 16, "bold"))
        style.configure("Meta.TLabel", font=("DejaVu Sans", 10), foreground=INK)
        style.configure("Status.TLabel", font=("DejaVu Sans", 10), foreground=INK)
        # the hint under each action tile: small enough to sit on one line
        style.configure("Hint.TLabel", font=("DejaVu Sans", 8), foreground=INK)
        # ttk's own controls default to a grey that belongs to no palette here
        for widget in ("TRadiobutton", "TCheckbutton"):
            style.configure(widget, background=BG, foreground=INK,
                            indicatorcolor=CARD)
            style.map(widget, background=[("active", BG)],
                      foreground=[("active", INK)])
        style.configure("TButton", background=CARD, foreground=INK,
                        bordercolor=CARD_EDGE, focuscolor=BG)
        style.map("TButton",
                  background=[("active", CARD_TINT), ("pressed", CARD_TINT)],
                  foreground=[("active", INK)])

        outer = ttk.Frame(self, padding=(14, 12))
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(side="top", fill="x", pady=(0, 10))
        try:
            self.logo = tk.PhotoImage(file=BANNER)
            self.logo_label = tk.Label(header, image=self.logo, bd=0,
                                       bg=BG)
            self.logo_label.pack(side="left")
        except tk.TclError:
            self.logo = None

        left = ttk.Frame(outer)
        left.pack(side="left", fill="y", padx=(0, 16))
        ttk.Label(left, text="Bays", font=("DejaVu Sans", 13, "bold")).pack(anchor="w")
        ttk.Label(left, text="messages waiting", font=("DejaVu Sans", 9),
                  foreground=INK).pack(anchor="w", pady=(0, 6))
        self.tree = ttk.Treeview(left, columns=("n",), show="tree",
                                 height=24, selectmode="browse")
        self.tree.column("#0", width=252)
        self.tree.column("n", width=54, anchor="e")
        self.tree.pack(fill="y", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_pick_bay)
        ttk.Button(left, text="Forget position", command=self.forget).pack(anchor="w", pady=(10, 0))
        self.counter = ttk.Label(left, text="", style="Status.TLabel")
        self.counter.pack(anchor="w", pady=(8, 0))
        for folder in self.bays:
            self.tree.insert("", "end", iid=folder.label, text=folder.label, values=("·",))

        right = ttk.Frame(outer)
        right.pack(side="left", fill="both", expand=True)

        self.banner = tk.Label(right, text="", bg="#fff3cd", fg="#7a5b00",
                               font=("DejaVu Sans", 10), anchor="w", padx=10, pady=7)

        # the header bar: who it is from, which bay and when, then the subject
        head = tk.Frame(right, bg="#ffffff", highlightbackground=CARD_EDGE,
                        highlightthickness=1)
        head.pack(fill="x")
        self.lbl_from = tk.Label(head, text="Choose a bay", anchor="w", justify="left",
                                 bg="#ffffff", fg=INK, font=("DejaVu Sans", 10),
                                 wraplength=900, padx=14, pady=0)
        self.lbl_from.pack(fill="x", padx=2, pady=(10, 0))
        self.lbl_meta = tk.Label(head, text="The 21 bays hold mail awaiting a decision; "
                                            "nothing here is a permanent home.",
                                 anchor="w", justify="left", bg="#ffffff", fg=INK,
                                 font=("DejaVu Sans", 9), wraplength=900, padx=14)
        self.lbl_meta.pack(fill="x", padx=2, pady=(1, 6))
        self.lbl_subject = tk.Label(head, text="", anchor="w", justify="left",
                                    bg="#ffffff", fg=INK,
                                    font=("DejaVu Sans", 15, "bold"),
                                    wraplength=900, padx=14)
        self.lbl_subject.pack(fill="x", padx=2, pady=(0, 12))

        body = ttk.Frame(right)
        body.pack(fill="both", expand=True)

        # the decision row and the status line are packed from the bottom first,
        # so a tall message body can never squeeze them off the window
        self.status = ttk.Label(right, text="", style="Status.TLabel")
        self.status.pack(side="bottom", anchor="w", pady=(10, 0))
        actions = ttk.Frame(right)
        actions.pack(side="bottom", fill="x", pady=(10, 0))

        self.text = tk.Text(body, wrap="word", font=("DejaVu Sans", 11),
                            bg=CARD, fg=INK, relief="flat",
                            padx=18, pady=14, insertwidth=0, height=8,
                            spacing1=2, spacing3=5)
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set, state="disabled")
        self.text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.btn_stay = self.action(actions, "stay", "Stays here",
                                    "already correctly placed", self.do_stay)
        self.btn_reloc = self.action(actions, "relocate", "Move on",
                                     "move to permanent folder",
                                     self.do_relocate)
        self.btn_misfile = self.action(actions, "alert", "Misfiled",
                                       "wrong bay — choose another",
                                       self.do_misfiled)
        self.btn_new = self.action(actions, "newfolder", "New folder",
                                   "move to new folder", self.do_new_folder)
        self.btn_trash = self.action(actions, "trash", "Trash",
                                     "move to trash folder",
                                     self.do_trash)

        for key, call in (("s", self.do_stay), ("r", self.do_relocate),
                          ("m", self.do_misfiled), ("n", self.do_new_folder),
                          ("t", self.do_trash)):
            self.bind(f"<KeyPress-{key}>", lambda e, c=call: c())

    def action(self, parent, icon, title, hint, command):
        column = len(parent.winfo_children())
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=column, sticky="nsew")
        parent.grid_columnconfigure(column, weight=1, uniform="action")
        image = self.icons.get(icon)
        button = tk.Button(frame, image=image, compound="top", text="  " + title,
                           font=("DejaVu Sans", 11, "bold"), relief="flat",
                           bg=CARD, fg=INK, activebackground=CARD_TINT,
                           activeforeground=INK,
                           highlightbackground=CARD_EDGE, highlightthickness=1,
                           bd=0, padx=8, pady=8, command=command,
                           cursor="hand2")
        button.image = image
        button.pack(fill="x")
        ttk.Label(frame, text=hint, style="Hint.TLabel", wraplength=162,
                  justify="center", anchor="center").pack(fill="x", pady=(4, 0))
        return button

    # ── counting, off the drawing thread ──
    def fill_counts(self):
        for folder in self.bays:
            try:
                headers = scan(folder.path)
                done = set(self.state.get(folder.label, []))
                left = sum(1 for h in headers if h["id"] not in done)
            except OSError:
                continue
            self.after(0, lambda f=folder, n=left: self.tree.exists(f.label)
                       and self.tree.set(f.label, "n", n))

    def watch_app(self):
        """Notice when Betterbird is closed (or opened) without a restart."""
        self.warn_if_running()
        self.after(15000, self.watch_app)

    def warn_if_running(self):
        if mm.running():
            self.banner.configure(text="Betterbird is open. Reading is safe; moving is "
                                       "blocked until it is closed — otherwise its own copy "
                                       "of the folder file would overwrite these moves when "
                                       "it quits.")
            self.banner.pack(fill="x", pady=(0, 8), before=self.lbl_subject.master)
            for b in (self.btn_stay, self.btn_reloc, self.btn_misfile):
                b.configure(state="disabled")
        else:
            self.banner.pack_forget()
            for b in (self.btn_stay, self.btn_reloc, self.btn_misfile):
                b.configure(state="normal")

    # ── a bay ──
    def busy(self, note):
        self.configure(cursor="watch")
        self.status.configure(text=note)
        self.update_idletasks()

    def idle(self):
        self.configure(cursor="")

    def on_pick_bay(self, _event=None):
        selection = self.tree.selection()
        if not selection:
            return
        label = selection[0]
        self.current = next(f for f in self.bays if f.label == label)
        self.busy(f"reading {label}…")
        headers = scan(self.current.path)
        self.idle()
        done = set(self.state.get(label, []))
        self.queue = sorted((h for h in headers if h["id"] not in done),
                            key=lambda h: h.get("ts", 0), reverse=True)
        self.show_next()

    def show_next(self):
        if not self.current:
            return
        if not self.queue:
            self.shown = None
            self.lbl_from.configure(text="")
            self.lbl_meta.configure(text=self.current.label)
            self.lbl_subject.configure(text="Bay clear — nothing left to look at.")
            self.set_body("")
            self.counter.configure(text=f"0 waiting in {self.current.label}")
            self.status.configure(text="Choose another bay.")
            self.tree.set(self.current.label, "n", 0)
            return
        message = self.queue[0]
        self.shown = message
        msg = read_at(self.current.path, message["offset"])
        self.lbl_from.configure(text=message["from"])
        self.lbl_meta.configure(text=f"{self.current.label}   ·   "
                                     f"{message.get('when') or message['date']}")
        self.lbl_subject.configure(text=message["subject"])
        self.set_body(body_text(msg))
        self.counter.configure(text=f"{len(self.queue)} waiting in {self.current.label}")
        self.status.configure(text="s — stays here   r — move on   m — misfiled   "
                                 "n — new folder   t — trash")

    def set_body(self, text):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text[:200000])
        self.text.configure(state="disabled")
        self.text.yview_moveto(0)

    # ── the three decisions ──
    def require_closed(self):
        if mm.running():
            messagebox.showwarning(
                "Betterbird is open",
                "Close Betterbird first. It holds the folder files open and would write "
                "its own copy back on exit, losing this move.")
            return False
        return bool(self.shown)

    def mark_done(self):
        if self.current and self.shown:
            self.state.setdefault(self.current.label, []).append(self.shown["id"])
            self.save_state()
        if self.queue:
            self.queue.pop(0)
        if self.current:
            self.tree.set(self.current.label, "n", len(self.queue))
        self.shown = None

    def resync(self):
        """After a move the folder file has been rewritten, so every saved offset
        is stale. Re-read the bay; done messages are already gone from it."""
        if not self.current:
            return
        done = set(self.state.get(self.current.label, []))
        self.queue = sorted((h for h in scan(self.current.path) if h["id"] not in done),
                            key=lambda h: h.get("ts", 0), reverse=True)

    def do_stay(self):
        if not self.shown:
            return
        self.mark_done()
        self.show_next()

    def do_relocate(self):
        if not self.require_closed():
            return
        FolderPicker(self, lambda folder: self.relocate_to(folder),
                     last=load_last_destination())

    def relocate_to(self, folder):
        self.busy(f"moving to {folder.label}…")
        moved = move_message(self.current.path, folder.path, self.shown["id"])
        self.idle()
        if not moved:
            messagebox.showerror("Not moved", "That message could not be found in the bay.")
            return
        if folder.key != "Trash":
            save_last_destination(folder)
        self.mark_done()
        self.resync()
        self.show_next()
        self.status.configure(text=f"Moved to {folder.label}.")

    def do_trash(self):
        """One click, no menu: the commonest destination of all."""
        if not self.require_closed():
            return
        trash = next((f for f in self.folders
                      if f.key == "Trash" and f.account == filing_account()), None)
        if trash is None:
            messagebox.showerror("No Trash folder", "The account's Trash folder was "
                                                   "not found in the store.")
            return
        self.relocate_to(trash)
        self.status.configure(text="Deleted — moved to Trash.")

    def do_new_folder(self):
        if not self.require_closed():
            return
        NewFolder(self, self.make_and_file)

    def make_and_file(self, name, parent, heading):
        account = filing_account()
        parts = (parent.parts + (name,)) if parent else (name,)
        key = " / ".join(parts)
        target = new_folder_path(parent, name, account)
        if os.path.exists(target) or os.path.exists(target + ".sbd"):
            messagebox.showerror("Already there", f"{key} already exists.")
            return
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            open(target, "wb").close()
        except OSError as exc:
            messagebox.showerror("Not made", f"Could not create the folder:\n{exc}")
            return
        save_menu_entry(key, heading, account)
        folder = Folder(key, target, account, False, parts)
        if not any(f.key == folder.key for f in self.folders):
            self.folders.append(folder)
        self.relocate_to(folder)
        self.status.configure(text=f"Made {key} under {heading} and filed the letter there.")

    def do_misfiled(self):
        if not self.require_closed():
            return
        Misfiled(self, self.shown, self.current, self.bays, self.apply_misfiled)

    def apply_misfiled(self, folder, scope, value, sweep):
        self.busy(f"moving to {folder.label}…")
        moved = move_message(self.current.path, folder.path, self.shown["id"])
        self.idle()
        if not moved:
            messagebox.showerror("Not moved", "That message could not be found in the bay.")
            return
        lines = [f"Moved to {folder.label}."]
        if scope != "none":
            cfg = load_cfg()
            changed, note = add_rule(cfg, folder.label, scope, value)
            lines.append(note)
            if changed:
                save_cfg(cfg)
                ok, line = regenerate_filters()
                lines.append("Filters regenerated." if ok else f"Filter rebuild failed: {line}")
                if sweep:
                    lines.append(self.sweep_inbox(scope, value, folder))
        self.mark_done()
        self.resync()
        self.show_next()
        self.status.configure(text=lines[0])
        messagebox.showinfo("Recorded", "\n".join(lines))

    def sweep_inbox(self, scope, value, folder):
        inbox = next((f for f in self.folders
                      if f.account == load_cfg().get("account") and f.label == "Inbox"), None)
        if not inbox:
            return "Inbox not found; nothing swept."
        moved = 0
        for header in scan(inbox.path):
            if scope == "address":
                hit = sender_address(header["from"]) == value.lower()
            elif scope == "domain":
                host = sender_domain(header["from"])
                hit = host == value.lower() or host.endswith("." + value.lower())
            elif scope == "subject":
                hit = value.lower() in header["subject"].lower()
            else:
                hit = value.lower().encode() in read_raw(inbox.path, header["offset"]).lower()
            if hit and move_message(inbox.path, folder.path, header["id"]):
                moved += 1
        return (f"{moved} further message(s) moved out of the Inbox." if moved
                else "Nothing else in the Inbox matched.")

    def forget(self):
        if messagebox.askyesno("Forget position",
                               "Forget how far you had got in every bay?\n\n"
                               "No mail is moved; each bay simply starts again from its "
                               "first message."):
            self.state = {}
            self.save_state()
            for folder in self.bays:
                if self.tree.exists(folder.label):
                    self.tree.set(folder.label, "n", "·")
            threading.Thread(target=self.fill_counts, daemon=True).start()
            if self.current:
                self.on_pick_bay()


def filing_account():
    """The account that holds the filing tree, as configured."""
    try:
        return json.load(open(CONFIG, encoding="utf-8")).get("account")
    except (OSError, ValueError):
        return None


def load_last_destination():
    """The folder last filed into, so the menu can open where it left off."""
    try:
        with open(LAST, encoding="utf-8") as fh:
            return json.load(fh).get("key")
    except (OSError, ValueError):
        return None


def save_last_destination(folder):
    try:
        os.makedirs(os.path.dirname(LAST), exist_ok=True)
        with open(LAST, "w", encoding="utf-8") as fh:
            json.dump({"key": folder.key, "label": folder.label}, fh)
    except OSError:
        pass


def new_folder_path(parent, name, account):
    """Where a new folder's mbox file belongs: beside its parent, or at the top."""
    mail = os.path.join(mm.profile(), "Mail", account)
    base = mail if parent is None else parent.path + ".sbd"
    return os.path.join(base, name)


def save_menu_entry(key, heading, account):
    """Record a new folder's heading, so the menu knows it without a hand edit."""
    try:
        with open(MENU, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        cfg = {"headings": [], "map": {}, "account": account}
    cfg.setdefault("headings", [])
    if heading not in cfg["headings"]:
        cfg["headings"].append(heading)
    cfg.setdefault("map", {})[key] = heading
    cfg["map"] = dict(sorted(cfg["map"].items(), key=lambda kv: kv[0].lower()))
    cfg.setdefault("account", account)
    tmp = MENU + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, MENU)


def load_menu():
    """Headings in order, the folder → heading map, and the account they refer to."""
    try:
        with open(MENU, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return [], {}, filing_account()
    return (list(data.get("headings") or []),
            dict(data.get("map") or {}),
            data.get("account") or filing_account())


def menu_groups(folders, needle=""):
    """Trash, then the configured headings, each holding its folders as a tree.

    The arrangement comes from ``mail_triage_menu.json``: a folder path mapped
    to a heading. Nothing that the map does not name is offered — which is how
    the 21 bays, `Incoming mail`, `Archives` and Betterbird's own Drafts, Inbox,
    Junk and Sent stay out of the list altogether.

    Returns [(label, folder_or_None, [nodes])]. A node is (folder, [child nodes]).
    A folder nests under its parent when both sit under the same heading;
    otherwise it starts a new branch in its own heading.
    """
    needle = (needle or "").strip().lower()
    headings, mapping, account = load_menu()
    by_key = {f.key: f for f in folders
              if f.parts and f.account == account and not f.is_bay}

    def matches(folder):
        return not needle or needle in folder.label.lower()

    def build(items):
        made, roots = {}, []
        for folder in items:
            made[folder.key] = (folder, [])
        for folder in items:
            node = made[folder.key]
            parent = made.get(" / ".join(folder.parts[:-1]))
            if parent is not None:
                parent[1].append(node)
            else:
                roots.append(node)
        return roots

    def prune(node):
        """During a search, keep a folder only if it or a descendant matches."""
        folder, children = node
        kept = [prune(c) for c in children]
        kept = [c for c in kept if c is not None]
        return (folder, kept) if (matches(folder) or kept) else None

    out = []
    trash = next((f for f in folders if f.key == "Trash" and f.account == account), None)
    if trash:
        out.append(("Trash", trash, []))

    for heading in headings:
        items = sorted((f for f in by_key.values() if mapping.get(f.key) == heading),
                       key=lambda f: [part.lower() for part in f.parts])
        if not items:
            continue
        roots = build(items)
        if needle:
            roots = [r for r in (prune(node) for node in roots) if r is not None]
        if roots:
            out.append((heading, None, roots))
    return out


class FolderPicker(tk.Toplevel):
    """Trash, then the filing tree. Never the bays."""

    def __init__(self, app, on_choice, last=None):
        super().__init__(app)
        self.title("Move to…")
        self.last = last
        self.configure(bg=BG)
        self.geometry("640x600")
        self.transient(app)
        self.grab_set()
        self.on_choice = on_choice
        self.folders = app.folders
        self.visible = []

        ttk.Label(self, text="Where does this belong?", padding=(14, 12, 14, 4),
                  font=("DejaVu Sans", 13, "bold")).pack(anchor="w")
        self.search = ttk.Entry(self, font=("DejaVu Sans", 11))
        self.search.pack(fill="x", padx=14, pady=(0, 2))
        ttk.Label(self, text="type to narrow the list; Trash is always first",
                  font=("DejaVu Sans", 9), foreground=INK).pack(anchor="w", padx=14)
        self.search.bind("<KeyRelease>", lambda e: self.fill())

        wrap = ttk.Frame(self, padding=(14, 10))
        wrap.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(wrap, show="tree", selectmode="browse")
        self.tree.pack(side="left", fill="both", expand=True)
        bar = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self.choose())
        self.tree.bind("<Return>", lambda e: self.choose())

        buttons = ttk.Frame(self, padding=14)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Move here", command=self.choose).pack(side="right", padx=8)
        self.fill()
        if self.last:
            self.reveal(self.last)
        self.search.focus_set()

    def fill(self):
        self.tree.delete(*self.tree.get_children())
        self.visible = {}
        needle = self.search.get().strip()
        for label, folder, children in menu_groups(self.folders, needle):
            if folder is not None:
                self.tree.insert("", "end", iid=f"f{id(folder)}", text=label)
                self.visible[f"f{id(folder)}"] = folder
            else:
                node = self.tree.insert("", "end", text=label, open=bool(needle))
                self._fill_children(node, children, open_all=bool(needle))

    def reveal(self, key):
        """Open the branch holding this folder and put the cursor on it."""
        for iid, folder in self.visible.items():
            if folder.key != key:
                continue
            node = self.tree.parent(iid)
            while node:
                self.tree.item(node, open=True)
                node = self.tree.parent(node)
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self.tree.see(iid)
            return True
        return False

    def _fill_children(self, parent, nodes, open_all=False):
        for folder, children in nodes:
            iid = f"f{id(folder)}"
            self.tree.insert(parent, "end", iid=iid, text=folder.parts[-1])
            self.visible[iid] = folder
            if children:
                self._fill_children(iid, children, open_all)
                self.tree.item(iid, open=open_all)

    def choose(self):
        selection = self.tree.selection()
        if not selection or selection[0] not in self.visible:
            return
        folder = self.visible[selection[0]]
        self.destroy()
        self.on_choice(folder)


class Misfiled(tk.Toplevel):
    """Where should it have gone, and what should the sorter learn?"""

    SCOPES = (("address", "This sender's address, for ever"),
              ("domain", "This sender's whole domain, for ever"),
              ("subject", "Anything with this phrase in the subject"),
              ("body", "Anything with this phrase in the body"),
              ("none", "Nothing — a one-off, no rule"))

    def __init__(self, app, message, current, bays, on_decide):
        super().__init__(app)
        self.title("Misfiled")
        self.configure(bg=BG)
        self.geometry("820x660")
        self.transient(app)
        self.grab_set()
        self.on_decide = on_decide
        self.bays = [b for b in bays if b.label != current.label]
        self.address = sender_address(message["from"])
        self.domain = sender_domain(message["from"])

        ttk.Label(self, text=message["subject"], font=("DejaVu Sans", 14, "bold"),
                  wraplength=760, justify="left").pack(anchor="w", padx=16, pady=(14, 2))
        ttk.Label(self, text=f"{message['from']}   ·   {current.label}",
                  font=("DejaVu Sans", 10), foreground=INK).pack(anchor="w", padx=16)

        body = ttk.Frame(self, padding=(16, 12, 16, 0))
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True)
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(20, 0))

        ttk.Label(left, text="Correct bay", font=("DejaVu Sans", 11, "bold")).pack(anchor="w")
        self.listbox = tk.Listbox(left, font=("DejaVu Sans", 11), activestyle="none",
                                  exportselection=False, height=15, relief="flat",
                                  highlightthickness=1, selectbackground="#cfe3ff",
                                  selectforeground=INK)
        for bay in self.bays:
            self.listbox.insert("end", bay.label)
        self.listbox.pack(fill="both", expand=True, pady=(6, 0))
        self.listbox.bind("<<ListboxSelect>>", lambda e: self.preview())

        ttk.Label(right, text="What should the sorter learn?",
                  font=("DejaVu Sans", 11, "bold")).pack(anchor="w")
        self.scope = tk.StringVar(value="address")
        for value, label in self.SCOPES:
            ttk.Radiobutton(right, text=label, value=value, variable=self.scope,
                            command=self.on_scope).pack(anchor="w", pady=1)
        self.entry = ttk.Entry(right, font=("DejaVu Sans", 11))
        self.entry.pack(fill="x", pady=(9, 3))
        self.entry.bind("<KeyRelease>", lambda e: self.preview())
        ttk.Label(right, text="the address, domain or phrase the rule will match",
                  font=("DejaVu Sans", 9), foreground=INK).pack(anchor="w")

        self.sweep = tk.BooleanVar(value=True)
        ttk.Checkbutton(right, text="Also clear matching mail out of the Inbox",
                        variable=self.sweep).pack(anchor="w", pady=(9, 0))

        ttk.Label(right, text="What the rule would do", font=("DejaVu Sans", 11, "bold")
                  ).pack(anchor="w", pady=(14, 2))
        self.impact = tk.Text(right, height=9, wrap="word", font=("DejaVu Sans", 10),
                              bg=CARD, relief="flat", padx=10, pady=8)
        self.impact.pack(fill="both", expand=True)
        self.impact.configure(state="disabled")

        buttons = ttk.Frame(self, padding=16)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Move and record", command=self.commit).pack(side="right", padx=8)
        ttk.Button(buttons, text="Test rule", command=self.preview).pack(side="right")

        self.on_scope()
        pick = os.environ.get("TRIAGE_DEMO_PICK")
        if pick:
            for index, bay in enumerate(self.bays):
                if bay.label == pick:
                    self.listbox.selection_set(index)
                    self.preview()
                    break

    def on_scope(self):
        scope = self.scope.get()
        value = {"address": self.address, "domain": self.domain}.get(scope, "")
        self.entry.configure(state="normal")
        self.entry.delete(0, "end")
        self.entry.insert(0, value)
        if scope == "none":
            self.entry.configure(state="disabled")
        self.preview()

    def chosen_bay(self):
        selection = self.listbox.curselection()
        return self.bays[selection[0]] if selection else None

    def preview(self):
        bay, scope = self.chosen_bay(), self.scope.get()
        value = self.entry.get().strip()
        self.impact.configure(state="normal")
        self.impact.delete("1.0", "end")
        if not bay:
            text = "Choose the bay it should have gone to."
        elif scope == "none":
            text = f"This message alone moves to {bay.label}. No rule is written."
        elif not value:
            text = "Type the phrase the rule should match."
        else:
            self.impact.insert("end", "testing…")
            self.impact.configure(state="disabled")
            self.update_idletasks()
            per, total = rule_matches(self.master.folders, scope, value, bay.label)
            lines = [f"{scope} “{value}” → {bay.label}", ""]
            if total:
                lines.append(f"Claims {total} message(s) now in:")
                for label, n in sorted(per.items(), key=lambda kv: -kv[1]):
                    lines.append(f"    {n:4d}   {label}")
                strays = sum(n for label, n in per.items() if label != bay.label)
                if strays:
                    lines += ["", f"{strays} of those would be pulled out of another bay — "
                                  f"check each is really {bay.label} business."]
            else:
                lines.append("Matches nothing now in the triage tree.")
            text = "\n".join(lines)
        self.impact.configure(state="normal")
        self.impact.delete("1.0", "end")
        self.impact.insert("1.0", text)
        self.impact.configure(state="disabled")

    def commit(self):
        bay = self.chosen_bay()
        if not bay:
            messagebox.showinfo("Choose a bay", "Pick the bay it should have gone to.")
            return
        scope, value = self.scope.get(), self.entry.get().strip()
        if scope != "none" and not value:
            messagebox.showinfo("Rule needs a value", "Type the phrase the rule should match.")
            return
        if scope == "domain" and not messagebox.askyesno(
                "The whole domain?",
                f"@{self.domain} covers every sender at that domain, not just this one. "
                f"Send them all to {bay.label}?"):
            return
        self.destroy()
        self.on_decide(bay, scope, value, self.sweep.get())


class NewFolder(tk.Toplevel):
    """Name a new folder, say where it lives and which heading it belongs under."""

    RESERVED = {"Incoming mail", "Trash", "Drafts", "Inbox", "Junk", "Sent"}
    BAD_ENDS = (".msf", ".dat", ".json", ".html", ".sqlite", ".sbd", ".tmp")

    def __init__(self, app, on_create):
        super().__init__(app)
        self.title("New folder")
        self.configure(bg=BG)
        self.geometry("580x600")
        self.transient(app)
        self.grab_set()
        self.on_create = on_create
        self.account = filing_account()
        self.folders = app.folders
        self.headings, self.mapping, _ = load_menu()
        self.by_iid = {}
        self.parent_choice = None

        ttk.Label(self, text="Where should the new folder go?",
                  font=("DejaVu Sans", 13, "bold")).pack(anchor="w", padx=14, pady=(12, 2))
        ttk.Label(self, text="choose the folder it sits inside, or the top level",
                  font=("DejaVu Sans", 9), foreground=INK).pack(anchor="w", padx=14, pady=(0, 6))

        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, padx=14)
        self.tree = ttk.Treeview(wrap, show="tree", selectmode="browse", height=11)
        bar = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.on_pick_parent)

        top = self.tree.insert("", "end", text=f"{self.account} — top level", open=True)
        self.fill_tree(top)

        form = ttk.Frame(self)
        form.pack(fill="x", padx=14, pady=(12, 0))
        ttk.Label(form, text="Name", font=("DejaVu Sans", 10, "bold")).pack(anchor="w")
        self.name = ttk.Entry(form, font=("DejaVu Sans", 12))
        self.name.pack(fill="x", pady=(2, 8))

        ttk.Label(form, text="Under which heading?", font=("DejaVu Sans", 10, "bold")).pack(anchor="w")
        row = ttk.Frame(form)
        row.pack(fill="x", pady=(2, 0))
        self.heading = tk.StringVar(value="Professional")
        for index, heading in enumerate(self.headings):
            ttk.Radiobutton(row, text=heading, value=heading, variable=self.heading).grid(
                row=0, column=index, sticky="w", padx=(0, 14))

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", padx=14, pady=12)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Create and file here", command=self.create).pack(side="right", padx=8)

        self.tree.selection_set(top)
        self.name.focus_set()
        self.bind("<Return>", lambda e: self.create())
        self.bind("<Escape>", lambda e: self.destroy())

    def fill_tree(self, top):
        mine = [f for f in self.folders
                if f.parts and f.account == self.account and not f.is_bay
                and f.parts[0] not in self.RESERVED]
        mine.sort(key=lambda f: [part.lower() for part in f.parts])
        made = {}
        for folder in mine:
            made[folder.key] = self.tree.insert(
                made.get(" / ".join(folder.parts[:-1]), top), "end",
                text=folder.parts[-1])
            self.by_iid[made[folder.key]] = folder

    def on_pick_parent(self, _event=None):
        selection = self.tree.selection()
        if not selection:
            return
        iid = selection[0]
        if iid in self.by_iid:
            self.parent_choice = self.by_iid[iid]
            heading = self.mapping.get(self.parent_choice.key)
            if heading in self.headings:
                self.heading.set(heading)
        else:
            self.parent_choice = None

    def create(self):
        name = self.name.get().strip()
        if not name:
            messagebox.showinfo("A name", "Type the name of the new folder.")
            return
        if "/" in name or "\\" in name:
            messagebox.showerror("Not that name", "A slash would split the name into "
                                 "folders. Use a plain name.")
            return
        if name.startswith(".") or name.lower().endswith(self.BAD_ENDS):
            messagebox.showerror("Not that name", "That ending belongs to a file the "
                                 "mail store uses itself. Choose another name.")
            return
        if name in self.RESERVED:
            messagebox.showerror("Not that name", f"\"{name}\" is Betterbird's own folder.")
            return
        parent = self.parent_choice
        parts = (parent.parts if parent else ()) + (name,)
        if any(f.key == " / ".join(parts) for f in self.folders):
            messagebox.showerror("Already there", " / ".join(parts) + " already exists.")
            return
        self.destroy()
        self.on_create(name, parent, self.heading.get())


def main():
    if not os.path.exists(CONFIG):
        raise SystemExit(f"no rule table at {CONFIG}")
    os.makedirs(BACKUPS, exist_ok=True)
    Triage().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
