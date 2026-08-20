"""
One-off migration (2026-08-20): Harris Projects has 8 real before/after post
examples (Tim's own team hand-editing AI drafts into the actual target voice)
sitting as plain text inside clients.style_rules. That's the single strongest
voice signal in the whole file, but style_rules is read by the model as
instructions/rules, not as writing samples to pattern-match against -- there's
a purpose-built mechanism for that (style_docs, "REFERENCE COPY -- study the
vocabulary, sentence rhythm, and voice") and it's empty for Harris.

This script adds the 8 "After" texts (the actual target-voice copy, not the
AI-slop "Before" drafts) to style_docs as 8 separate reference files. It does
NOT touch style_rules -- the full before/after comparison stays there too,
since it also carries separate instructional value (showing what changes and
why). This is additive only: nothing is deleted, so it's safe to re-run
(re-running will just add duplicate rows -- check style_docs first if
re-running).

Run ONCE on the server:
    cd /var/www/hemingway
    venv/bin/python3 migrate_harris_examples.py   (or: python3 migrate_harris_examples.py
                                                     if there's no venv)
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'hemingway.db')

# The 8 "After" texts, pulled verbatim from Harris Projects' style_rules field.
EXAMPLES = [
    (
        "harris-post-1-after.txt",
        "Hey guys, we were called out to this job and found out that this would require a full "
        "replacement of the south wall of the entire house. And this involved some real decisions.\n\n"
        "We gave the owner two options for the rebuild. Steel or a wood LVL shear wall. Steel had real "
        "appeal structurally, but the lead time was 5 weeks on the order before installation could even "
        "begin.\n\n"
        "That's 5 weeks a rental property sits empty. That's a lot of rental revenue. The LVL shear wall "
        "got us moving right away and still gave us solid shear capacity when following the engineers "
        "specs.\n\n"
        "We took the wood option, which included LVL stud walls and sheathing diaphragm. This helps to "
        "prevent lateral movement in the structure.\n\n"
        "A much stronger building, back on the rental market 5 weeks sooner than the steel route would "
        "have allowed."
    ),
    (
        "harris-post-2-after.txt",
        "We just wrapped up Andersen certification, which means we're now certified to install and "
        "repair Andersen doors and windows to manufacturer spec.\n\n"
        "The certification is not just about getting the piece of paper. It's about understanding the "
        "product at a deeper level so when we install or repair your windows and doors, they perform "
        "the way they're supposed to.\n\n"
        "Windows and doors take a beating on the Gulf Coast from the salt air, wind-driven rain, and "
        "constant humidity. If they're not installed correctly from the start, you're looking at leaks, "
        "drafts, and callbacks. We don't do callbacks.\n\n"
        "If you've got Andersen door or window needs, whether it's a new install or a repair, reach out "
        "- harrisprojects.co"
    ),
    (
        "harris-post-3-after.txt",
        "We added nickel gap to the walls on this build, but we did something a little different. We "
        "put drywall behind the nickel gap before we installed it."
    ),
    (
        "harris-post-4-after.txt",
        "We're always happy to make adjustments along the way to make sure the homeowner gets exactly "
        "what they're looking for.\n\n"
        "When the owner recently walked through the progress on this project, the bathrooms really "
        "stood out compared to all the updates happening throughout the rest of the home.\n\n"
        "The cultured marble built-in tub and tile shower had been here since the early 2000s, and with "
        "the rest of the renovation already underway, he decided it made sense to go ahead and update "
        "this bathroom along with the primary suite upstairs.\n\n"
        "So, out it all came. We took both bathrooms down to the studs and are starting fresh.\n\n"
        "Next up here: a tiled inset and freestanding soaker tub that will completely change the look "
        "and feel of the space."
    ),
    (
        "harris-post-5-after.txt",
        "Here's the view from today's job site. We're out here repairing this beachfront deck, "
        "replacing the posts and railing so it can handle the coastal weather. It's still a full day of "
        "work, measuring, cutting, building, but every now and then, you look up and remember where you "
        "are. Office views are not created equal. This one's pretty hard to beat."
    ),
    (
        "harris-post-6-after.txt",
        "Some might say we're a little too particular about how we waterproof our sliding glass doors. "
        "But on the Gulf Coast you can't be too careful because this is where a lot of water intrusion "
        "starts if it isn't done right.\n\n"
        "As the video outlines every layer reinforces the one behind it. That overlap is what keeps "
        "this system working when you've got wind-driven rain and salt air hitting these doors "
        "constantly.\n\n"
        "Getting this right at the rough out stage is a whole lot easier than trying to chase down "
        "water damage once the walls are closed up and finished."
    ),
    (
        "harris-post-7-after.txt",
        "On this build, we upgraded the subfloor throughout the entire home to 1 1/8-inch AdvanTech "
        "instead of the standard 3/4-inch plywood.\n\n"
        "Code tells you the minimum. We're more interested in how the house will hold up over time.\n\n"
        "That extra thickness gives the floor system greater strength and stiffness, resulting in less "
        "flex and movement. And AdvanTech is built to handle moisture exposure better - something that "
        "matters when you're building in Gulf Coast conditions.\n\n"
        "The subfloor is underneath everything else in the house. If it starts moving, swelling, or "
        "creating squeaks down the road, fixing it isn't simple.\n\n"
        "Nobody is going to walk into this house and notice the upgraded subfloor. But years from now, "
        "they'll notice how solid the house still feels.\n\n"
        "That's the kind of upgrade we think is worth making."
    ),
    (
        "harris-post-8-after.txt",
        "On this build, we turned a basic wall into a custom entertainment center that gives the home a "
        "more finished, high-end feel.\n\n"
        "We recessed the 70-inch TV into the wall and added an electric fireplace below it that looks "
        "good and actually puts out heat during the cooler months.\n\n"
        "Behind it, we built a hidden access panel for the Wi-Fi equipment, modem, and wiring. "
        "Everything stays out of sight, but when something needs to be serviced or replaced, you can "
        "get to it without opening up the wall.\n\n"
        "It's a cleaner look for guests and a smarter setup for the homeowner.\n\n"
        "Building or renovating on the Gulf Coast? We'd be happy to talk about your project.\n\n"
        "Comment: \"Connect\" and we'll get in touch with you."
    ),
]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    row = conn.execute("SELECT id FROM clients WHERE name LIKE '%Harris%'").fetchone()
    if not row:
        print("No client matching '%Harris%' found -- aborting, nothing changed.")
        return
    client_id = row['id']

    existing = {r['filename'] for r in conn.execute(
        'SELECT filename FROM style_docs WHERE client_id = ?', (client_id,)
    )}

    added = 0
    for filename, content in EXAMPLES:
        if filename in existing:
            print(f"SKIP (already present): {filename}")
            continue
        conn.execute(
            'INSERT INTO style_docs (client_id, filename, content) VALUES (?, ?, ?)',
            (client_id, filename, content)
        )
        added += 1
        print(f"ADDED: {filename}")

    conn.commit()
    conn.close()
    print(f"\nDone. {added} reference doc(s) added for client_id={client_id}.")
    print("Nothing in style_rules was touched. Check Hemingway -> Harris Projects -> "
          "Style & Voice -> Reference copy to confirm.")


if __name__ == '__main__':
    main()
