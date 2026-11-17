# Trencher (prototype)

A clearance toolbar for the Thunderbird/Betterbird message pane. One letter at a
time, five decisions, each a single click: **Stays here · Move on · New folder ·
Trash · Spam**.

The point is not the buttons but where they sit. A client shows a dozen actions
when a message is opened — reply, forward, archive, spam, delete, more — none of
which answers the question the reader actually has: *what do I do with this one,
now?* Trencher puts that question first, and the answer is always one of five.

## Status

Prototype, 0.1.4, November 2026. All five decisions have been exercised against a
sandbox profile and verified on disk. It has not been reviewed by anyone else, is
not signed, and is not affiliated with the Thunderbird or Betterbird projects.

## Installing it for a trial

An unsigned add-on will not run in a release or ESR build, so load it temporarily:

1. Open **Tools ▸ Add-ons and Themes**, then the gear menu ▸ **Debug Add-ons**
   (or navigate to `about:debugging#/runtime/this-application`).
2. Choose **Load Temporary Add-on…** and select `manifest.json` from the unpacked
   source directory.
3. Open any message. A **Trencher — what do I do with this one?** button appears in
   the message header. Click it.

A temporary add-on disappears when the client is restarted; nothing persists and
nothing is installed into the profile. For permanent use the package must be signed
(addons.mozilla.org, or Betterbird's own add-on site).

## The five decisions

| Decision | What it does | API |
|---|---|---|
| Stays here | Marks the letter read and closes the panel | `messages.update` |
| Move on | Shows the destination list; moves on choice | `messages.move` |
| New folder | Name, parent and create; files the letter there | `folders.create`, `messages.move` |
| Trash | Moves the letter to the account's Trash | `messages.delete` |
| Spam | Marks it spam; the client's own filter learns | `messages.update` |

The Spam glyph is adapted from Betterbird's own spam icon (a flame), with the
context-fill colours that a WebExtension cannot render replaced by concrete ones;
both are MPL 2.0.

The destination list is grouped under the reader's own headings — Urgent, Professional, Administrative, Personal, Agentic — carried in `menu-map.js`, a folder the arrangement does not name takes the heading of its nearest named ancestor, so a matter created under an existing matter's parent is classified at once; only folders with no named ancestor fall into "Everything else". It excludes Trash and Spam (they have their own buttons) and
the account root, and offers the folder last filed into first.

## Files

    manifest.json        MV3 manifest (current; needs the client's own signing)
    manifest-mv2.json    MV2 variant, the one used in the sandbox trials
    background.js        state, and one self-test for the sandbox only
    popup.html/css/js    the panel: five tiles, destination list, new-folder form
    icons/trencher.svg   the toolbar mark (monochrome, per the house style)

## Known limitations

- **Unsigned**, so it must be loaded temporarily or signed before distribution.
- The **MV2 manifest** is what has been exercised; the MV3 build is included but
  unproven in this version of the client.
- **No backups.** Unlike the standalone Trencher program, this add-on delegates
  every move to the client, which does not take a per-message backup. A mis-click
  is recoverable from Trash or undone by hand, not from a copy.
- **Spam is a learning signal**, not a rule about the sender: the client's adaptive
  filter is trained by the marking.
- The background **self-test** (create a folder, move a letter, mark one junk) writes
  its report to extension storage; in the sandbox it produced no record, so treat
  that path as unverified.

## Provenance

Conceived by Anthony John Hunter Morris KC, King's Counsel, Brisbane: the five
decisions, the like-with-like arrangement, the menu drawn from headings rather
than storage, and the mark. Implemented and tested by DeepSeek V4 Flash acting as
the Barrister's Assistant. Offered to the Betterbird community for discussion, with
no claim of affiliation.

## Licence

Mozilla Public License 2.0 — the same licence as Thunderbird and Betterbird,
whose code this extends and whose formats it works with. The full text is in
`LICENSE`, and each source file carries the standard notice.
