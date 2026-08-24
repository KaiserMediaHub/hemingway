"""
Recovery script (2026-08-24): Hemingway's production database
(/var/www/hemingway/data/hemingway.db) was wiped during a service restart on
2026-08-20 -- every client, style rule, reference doc, and post history was
lost. Root cause not fully confirmed (ruled out: git, network storage mount,
cron job). There was no backup on the server and no Hetzner snapshot, so
everything except Harris Projects is unrecoverable.

Harris Projects IS recoverable because Ben pasted the client's complete
style_rules text into chat while we were diagnosing a separate issue, just
before the database was wiped. This script re-creates that one client exactly
as it was, verbatim, then re-adds the 8 before/after reference docs (same
content as migrate_harris_examples.py, folded in here so this is a single
run).

Safe to re-run: checks for an existing 'Harris Projects' client by name before
inserting, so running this twice won't create a duplicate client or duplicate
reference docs.

Run ONCE on the server:
    cd /var/www/hemingway
    python3 restore_harris_client.py
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'hemingway.db')

CLIENT_NAME = 'Harris Projects'

STYLE_RULES = """Harris Projects comes right from Tim’s voice. We are regular people, who take vacations, want to enjoy time off with their families. We’re doing life and doing great work.
It’s ok to say the last contractor did something wrong, but word it… this is not up to our personal standards. Don’t bash the past person.
Overall, let's try to avoid comparisons. Let's just focus on what works, and how we do it.
Important: style needs to feel loose. Longer sentences that could verge on run-on sentences. Feels very conversational and on the fly. Now, when explaining technical information make sure to be precise as it is important to explain things correctly within the construction industry.
Important: Vary the intros so they don't ALL sounds the same. These are some ideas on ways to start posts, but DO NOT start every post with one of these. These are just ideas:
Hey guys, on this project…
I was looking at this…
While I was on site the other day.
When thinking about how I would build this..
Never word maximizers (“No guarantees”)
- Locked in
- Perfect
- Rock-solid
- Last for 40 years
- For the long haul
- For years to come
Use words such as house or home instead of build, property, or structure.
Example:
Post 1:
Before:
Full south wall replacement on a Gulf Coast rental property, and the rebuild involved some real decisions.
We gave the owner two options for the rebuild. Steel or a wood LVL shear wall. Steel had real appeal structurally, but the lead time was 5 weeks on the order before installation could even begin.
That's 5 weeks a rental property sits empty. The LVL shear wall got us moving right away and still gave us solid shear capacity when designed correctly.
Doing it right in wood meant converting the doors to windows for full sheathing coverage, laying half-inch CDX across the entire ceiling, and building a new LVL stud wall to replace what had been open railing.
That wall is sheathed in 1 1/8 inch Advantech subfloor. Together those components form a diaphragm that locks the structure against lateral movement.
A much stronger building, back on the rental market 5 weeks sooner than the steel route would have allowed.
After:
Hey guys, we were called out to this job and found out that this would require a full replacement of the south wall of the entire house. And this involved some real decisions.
We gave the owner two options for the rebuild. Steel or a wood LVL shear wall. Steel had real appeal structurally, but the lead time was 5 weeks on the order before installation could even begin.
That's 5 weeks a rental property sits empty. That's a lot of rental revenue. The LVL shear wall got us moving right away and still gave us solid shear capacity when following the engineers specs.
We took the wood option, which included LVL stud walls and sheathing diaphragm. This helps to prevent lateral movement in the structure.
A much stronger building, back on the rental market 5 weeks sooner than the steel route would have allowed.
Post 2:
Before:
Anytime you get the opportunity to expand your knowledge or experience level, take it.
I just wrapped up Andersen certification, which means we're now certified to install and repair Andersen doors and windows to manufacturer spec. This isn't just a piece of paper. It's about understanding the product at a deeper level so when we install or repair your windows and doors, they perform the way they're supposed to.
Windows and doors take a beating on the Gulf Coast. Salt air, wind-driven rain, constant humidity. If they're not installed correctly from the start, you're looking at leaks, drafts, and callbacks. We don't do callbacks.
If you've got Andersen door or window needs, whether it's a new install or a repair, reach out.
After:
We just wrapped up Andersen certification, which means we're now certified to install and repair Andersen doors and windows to manufacturer spec.
The certification is not just about getting the piece of paper. It's about understanding the product at a deeper level so when we install or repair your windows and doors, they perform the way they're supposed to.
Windows and doors take a beating on the Gulf Coast from the salt air, wind-driven rain, and constant humidity. If they're not installed correctly from the start, you're looking at leaks, drafts, and callbacks. We don't do callbacks.
If you've got Andersen door or window needs, whether it's a new install or a repair, reach out - harrisprojects.co
Post 3:
Before:
We added nickel gap to the walls on this build, but we did something a little different behind it that most people skip. We put drywall behind the nickel gap before we installed it.
After:
We added nickel gap to the walls on this build, but we did something a little different. We put drywall behind the nickel gap before we installed it.
Post 4:
Before:
We're always happy to make adjustments on a project to get the owner exactly what they're looking for.
When the owner toured the progress of this project recently the out-of-date bathrooms stuck out in contrast to the progress we have made on the other portions of the renovation.
The cultured marble built-in tub and tile shower had been in here since the early 2000s.
So he decided both this bathroom and the primary suite upstairs were worth renovating while the project was already moving.
We got them ripped out and down to the studs.
Soon we will have a tiled inset and a standing soaker tub in place of what was there before.
After:
We’re always happy to make adjustments along the way to make sure the homeowner gets exactly what they’re looking for.
When the owner recently walked through the progress on this project, the bathrooms really stood out compared to all the updates happening throughout the rest of the home.
The cultured marble built-in tub and tile shower had been here since the early 2000s, and with the rest of the renovation already underway, he decided it made sense to go ahead and update this bathroom along with the primary suite upstairs.
So, out it all came. We took both bathrooms down to the studs and are starting fresh.
Next up here: a tiled inset and freestanding soaker tub that will completely change the look and feel of the space.
Post 5:
Before:
Not a bad view from the job site today. We’re out here working on a beachfront deck, replacing the posts and railing, and making sure it’s built to withstand coastal weather. Still a full day of measuring, cutting, and building, but there are definitely worse places to put in a day’s work. Office views are not created equal. This one's pretty hard to beat.
After:
Here's the view from today's job site. We're out here repairing this beachfront deck, replacing the posts and railing so it can handle the coastal weather. It's still a full day of work, measuring, cutting, building, but every now and then, you look up and remember where you are. Office views are not created equal. This one's pretty hard to beat.
Post 6:
Before:
"Some might say we're a little too particular about how we waterproof our sliding glass doors. But on the Gulf Coast you can't be too careful because this is where a lot of water intrusion starts if it isn't done right.
We start it off by laying a peel-and-stick membrane across the pan and up both sides of the opening. Then we lay down some stainless steel wall flashing on top with a 5x5 profile, then we lay over 12 inches of membrane running up the wall behind it.
The pan cap finishes it off, lapping down over the edge so any water that gets in is directed away from the home instead of sitting there soaking into the framing.
Every layer reinforces the one behind it. That overlap is what keeps this system working when you've got wind-driven rain and salt air hitting these doors constantly.
Getting this right at the rough out stage is a whole lot easier than trying to chase down water damage once the walls are closed up and finished. "
After:
"Some might say we're a little too particular about how we waterproof our sliding glass doors. But on the Gulf Coast you can't be too careful because this is where a lot of water intrusion starts if it isn't done right.
As the video outlines every layer reinforces the one behind it. That overlap is what keeps this system working when you've got wind-driven rain and salt air hitting these doors constantly.
Getting this right at the rough out stage is a whole lot easier than trying to chase down water damage once the walls are closed up and finished."
Post 7:
Before:
We upgraded the subfloor throughout this entire home to an inch and an eighth Advantech. Three-quarter inch plywood is standard code.
The extra thickness gives you more structural strength and better shear capacity across the entire floor system. When you're building on the Gulf Coast, that matters. The subfloor has to handle humidity, salt air, and the kind of loads that come with coastal storms.
A thicker, more stable base means the floor system doesn't flex or shift the way standard plywood does over time.
The subfloor is the foundation for everything that goes on top of it. If it moves, creaks, or fails down the road, you're dealing with bigger problems that are a lot harder to fix.
It's the upgrade most people never see, but it's the kind of decision that makes the difference in how a house holds up.
Looking to build or renovate a Gulf Coast home, get in touch.
After:
On this build, we upgraded the subfloor throughout the entire home to 1 1/8-inch AdvanTech instead of the standard 3/4-inch plywood.
Code tells you the minimum. We’re more interested in how the house will hold up over time.
That extra thickness gives the floor system greater strength and stiffness, resulting in less flex and movement. And AdvanTech is built to handle moisture exposure better - something that matters when you’re building in Gulf Coast conditions.
The subfloor is underneath everything else in the house. If it starts moving, swelling, or creating squeaks down the road, fixing it isn’t simple.
Nobody is going to walk into this house and notice the upgraded subfloor. But years from now, they’ll notice how solid the house still feels.
That’s the kind of upgrade we think is worth making.
Post 8:
Before:
On this project, we built out a custom entertainment center. It takes a boring space and makes it feel like a more premium rental.
The setup centers around a 70-inch TV with an electric fireplace insert below it. The fireplace looks like the real thing and puts out actual heat, which guests appreciate more than you'd think during those cooler months of the season. The TV itself recesses into the wall for that clean, flush look.
We added a hidden access panel behind the setup for all the Wi-Fi equipment and modem. No exposed cords running down the wall, no tech clutter sitting out where guests can mess with it.
When anything  needs updating or troubleshooting, you've got clean access without tearing into drywall.
Want to build a home on the Gulf Coast, we'd be happy to talk with you abou it - https://harrisprojects.co/
After:
On this build, we turned a basic wall into a custom entertainment center that gives the home a more finished, high-end feel.
We recessed the 70-inch TV into the wall and added an electric fireplace below it that looks good and actually puts out heat during the cooler months.
Behind it, we built a hidden access panel for the Wi-Fi equipment, modem, and wiring. Everything stays out of sight, but when something needs to be serviced or replaced, you can get to it without opening up the wall.
It’s a cleaner look for guests and a smarter setup for the homeowner.
Building or renovating on the Gulf Coast? We’d be happy to talk about your project.
Comment: "Connect" and we'll get in touch with you.
------
Harris Projects: more requested changes to writing style
- Make the writing sound more personal and more like Tim.
- Reduce language that feels monotone, robotic, or overly polished.
- Keep posts clearer and easier to understand for a normal audience.
- Avoid word maximizers and exaggerated phrasing like overly absolute or hype-heavy language.
- Avoid guarantees or hard claims that can’t truly be promised.
- Avoid lines implying things are 100% certain, “locked in,” or “never going anywhere.”
- Avoid wording that criticizes other builders, contractors, or past work too directly.
- Do not describe past contractors’ mistakes in a way that could sound accusatory or create risk.
- Focus on what Harris Projects does well, rather than contrasting with what others did wrong.
- If contrast is needed, make it softer and broader, not aimed at a specific contractor.
- Emphasize educational, trust-building language.
- Keep enough detail for platform performance, but put the most engaging/human part first.
- Use copy that helps clients understand why Harris does things a certain way.
- Make content support Tim’s sales process by building trust and credibility.
- For Instagram especially, lean into more conversational, story-driven, Tim-centric content.
Some notes from a Harris Projects meeting.
- Let's be more vague with Harris Projects writings.
Don't make absolutes:
- Hurricane will never knock down this house.
- We always do everything above and beyond code.
Post written structure:
What are we looking at, What are we trying to do, how are we doing it, what is the benefit.
Educational post vs beauty post."""

# Same 8 reference examples as migrate_harris_examples.py.
EXAMPLES = [
    ("harris-post-1-after.txt",
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
     "have allowed."),
    ("harris-post-2-after.txt",
     "We just wrapped up Andersen certification, which means we're now certified to install and "
     "repair Andersen doors and windows to manufacturer spec.\n\n"
     "The certification is not just about getting the piece of paper. It's about understanding the "
     "product at a deeper level so when we install or repair your windows and doors, they perform "
     "the way they're supposed to.\n\n"
     "Windows and doors take a beating on the Gulf Coast from the salt air, wind-driven rain, and "
     "constant humidity. If they're not installed correctly from the start, you're looking at leaks, "
     "drafts, and callbacks. We don't do callbacks.\n\n"
     "If you've got Andersen door or window needs, whether it's a new install or a repair, reach out "
     "- harrisprojects.co"),
    ("harris-post-3-after.txt",
     "We added nickel gap to the walls on this build, but we did something a little different. We "
     "put drywall behind the nickel gap before we installed it."),
    ("harris-post-4-after.txt",
     "We're always happy to make adjustments along the way to make sure the homeowner gets exactly "
     "what they're looking for.\n\n"
     "When the owner recently walked through the progress on this project, the bathrooms really "
     "stood out compared to all the updates happening throughout the rest of the home.\n\n"
     "The cultured marble built-in tub and tile shower had been here since the early 2000s, and with "
     "the rest of the renovation already underway, he decided it made sense to go ahead and update "
     "this bathroom along with the primary suite upstairs.\n\n"
     "So, out it all came. We took both bathrooms down to the studs and are starting fresh.\n\n"
     "Next up here: a tiled inset and freestanding soaker tub that will completely change the look "
     "and feel of the space."),
    ("harris-post-5-after.txt",
     "Here's the view from today's job site. We're out here repairing this beachfront deck, "
     "replacing the posts and railing so it can handle the coastal weather. It's still a full day of "
     "work, measuring, cutting, building, but every now and then, you look up and remember where you "
     "are. Office views are not created equal. This one's pretty hard to beat."),
    ("harris-post-6-after.txt",
     "Some might say we're a little too particular about how we waterproof our sliding glass doors. "
     "But on the Gulf Coast you can't be too careful because this is where a lot of water intrusion "
     "starts if it isn't done right.\n\n"
     "As the video outlines every layer reinforces the one behind it. That overlap is what keeps "
     "this system working when you've got wind-driven rain and salt air hitting these doors "
     "constantly.\n\n"
     "Getting this right at the rough out stage is a whole lot easier than trying to chase down "
     "water damage once the walls are closed up and finished."),
    ("harris-post-7-after.txt",
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
     "That's the kind of upgrade we think is worth making."),
    ("harris-post-8-after.txt",
     "On this build, we turned a basic wall into a custom entertainment center that gives the home a "
     "more finished, high-end feel.\n\n"
     "We recessed the 70-inch TV into the wall and added an electric fireplace below it that looks "
     "good and actually puts out heat during the cooler months.\n\n"
     "Behind it, we built a hidden access panel for the Wi-Fi equipment, modem, and wiring. "
     "Everything stays out of sight, but when something needs to be serviced or replaced, you can "
     "get to it without opening up the wall.\n\n"
     "It's a cleaner look for guests and a smarter setup for the homeowner.\n\n"
     "Building or renovating on the Gulf Coast? We'd be happy to talk about your project.\n\n"
     "Comment: \"Connect\" and we'll get in touch with you."),
]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    existing = conn.execute(
        'SELECT id FROM clients WHERE name = ?', (CLIENT_NAME,)
    ).fetchone()

    if existing:
        client_id = existing['id']
        print(f"Client '{CLIENT_NAME}' already exists (id={client_id}) -- updating style_rules "
              f"to the restored text instead of inserting a duplicate.")
        conn.execute('UPDATE clients SET style_rules = ? WHERE id = ?', (STYLE_RULES, client_id))
    else:
        cursor = conn.execute(
            'INSERT INTO clients (name, style_rules) VALUES (?, ?)', (CLIENT_NAME, STYLE_RULES)
        )
        client_id = cursor.lastrowid
        print(f"Created client '{CLIENT_NAME}' (id={client_id}) with restored style_rules "
              f"({len(STYLE_RULES)} chars).")

    conn.commit()

    existing_docs = {r['filename'] for r in conn.execute(
        'SELECT filename FROM style_docs WHERE client_id = ?', (client_id,)
    )}

    added = 0
    for filename, content in EXAMPLES:
        if filename in existing_docs:
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
    print(f"\nDone. Harris Projects restored (client_id={client_id}), {added} reference doc(s) added.")


if __name__ == '__main__':
    main()
