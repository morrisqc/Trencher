# Trencher

Trencher is a small, opinionated tool for clearing an inbox. It proceeds from one
observation: whatever else may be done with an incoming message, the immediate
decision is always one of five — **stays here**, **move on**, **new folder**,
**trash**, **spam**. Trencher puts those five decisions in front of the reader,
one click each, and gets out of the way.

It comes in two parts.

**The add-on** (`addon/`) is a Betterbird/Thunderbird extension. Open a message
in any folder and a toolbar offers the five actions:

| Action | What it does |
| --- | --- |
| Stays here | Already correctly placed; nothing to do |
| Move on | File it in a permanent folder, chosen from a list grouped under your own headings |
| New folder | Create a folder or sub-folder, and file the message into it |
| Trash | Send it to the Trash folder |
| Spam | Mark it as spam; the client's own adaptive filter learns from it |

The destination list is grouped under headings you define, and a folder you have
not yet classified inherits the heading of its nearest classified ancestor — so a
matter created under `matters - active` is classified the moment it exists.

**The desktop program** (`app/mail_triage_gui.py`) is a companion for a backlog:
it walks messages in a set of holding folders — bays — one at a time, showing
the same decisions, and records the choices as filing rules so that the same sender or
domain is classified automatically thereafter. It is a Tk application and needs
only the Python standard library.

## Installing the add-on in Betterbird or Thunderbird

The packaged `.xpi` is unsigned, and current Betterbird and Thunderbird builds enforce
signatures: an unsigned add-on cannot be installed permanently, and setting
`xpinstall.signatures.required` to `false` does not help, because the client clears that
preference at startup (verified on Betterbird 153.7.0esr with both `prefs.js` and
`user.js`).

Until a signed build is available, load it for the session instead:

1. Open **`about:debugging`** in the client.
2. Choose **This Thunderbird** in the left-hand column.
3. **Load Temporary Add-on…** and select the `.xpi`.

The toolbar then works fully; it disappears when the client is restarted. Signing through
`addons.thunderbird.net` is what makes an installation permanent.

## Classifying your own folders

Copy `addon/menu-map.js` and edit it, or generate it from an arrangement file:

```sh
python3 tools/make_menu_map.py my-arrangement.json addon/menu-map.js
```

The rules are set out at the head of that file. A folder the arrangement does not
mention is never hidden — it appears under *Everything else*, so the list stays
usable while you build the arrangement up.

## Building the package

```sh
cp addon/manifest-mv2.json /tmp/mv2/manifest.json
cp addon/*.js addon/*.css addon/*.html addon/LICENSE addon/README.md /tmp/mv2/
cp -r addon/icons /tmp/mv2/
cd /tmp/mv2 && zip -qr trencher.xpi .
```

## Confidentiality

This repository contains no personal folder names, no correspondents' addresses
and no filing rules. The example arrangement in `addon/menu-map.js` is
illustrative; anyone deploying Trencher supplies their own.

## Licence

Mozilla Public License 2.0. See `LICENSE`.
