import re

STYLE_PROMPTS = {
    'thought-leader': (
        'You write in the style of a confident LinkedIn thought leader. Your writing is authoritative, '
        'direct, and opinionated. You make strong claims backed by experience. You use short punchy '
        'sentences mixed with deeper insight. You never hedge unnecessarily. You write like someone who '
        'has earned their perspective and is not afraid to share it. No buzzwords. No fluff. No '
        'AI-sounding phrases.'
    ),
    'conversational': (
        'You write in a warm, conversational tone like a smart, thoughtful person talking directly to '
        'a colleague or friend. You write in first person. You use natural language, occasional sentence '
        'fragments, and real human rhythm. You are never formal. You are never stiff. You write the way '
        'a confident person actually talks.'
    ),
    'storyteller': (
        'You write like a skilled storyteller. You open with a scene, a moment, or an observation that '
        'hooks the reader immediately. You build narrative momentum. You make the reader feel like they '
        'are there. You find the human truth in whatever the speaker said and lead with that. Your '
        'writing has texture, emotion, and forward pull.'
    ),
    'punchy': (
        'You write with extreme economy. Short sentences. Hard stops. No filler words. No '
        'throat-clearing. Every line must earn its place. You write like someone who respects the '
        "reader's time. High contrast between big ideas and simple language. No jargon. No padding. "
        'Think: a journalist who got paid by the cut, not the word.'
    ),
}

LENGTH_INSTRUCTIONS = {
    'super-short': (
        'Write an extremely short post of 1 to 3 sentences only. One punchy idea. '
        'No buildup, no closing line, no hashtags. Just the sharpest possible version of the core point.'
    ),
    'short': (
        'Write a short post of 3 to 5 focused paragraphs. Get in, say the thing, get out. '
        'Every word must be there for a reason.'
    ),
    'medium': (
        'Write a medium-length post of 5 to 8 paragraphs. Develop the idea with enough depth '
        'to be genuinely memorable.'
    ),
    'long': (
        'Write a longer post of 8 or more paragraphs. Develop the full narrative arc with '
        'supporting detail, texture, and a strong close.'
    ),
}

# These two are DEFAULTS ONLY as of 2026-08-24 -- the live values are stored
# in the global_style table (db.py) and editable from the "Global Style"
# button in Hemingway's header. These constants exist to (a) seed that table
# the first time it's empty, and (b) be the fallback in build_system_prompt/
# build_review_system_prompt when no override is passed in (keeps every
# existing caller/test that doesn't know about global_style working
# unchanged). Ben's ask: "is there a spot where I can edit the global style?
# Things that every client needs" -- previously this required a code change.
DEFAULT_GLOBAL_STYLE_DOC = '''GLOBAL STYLE STANDARDS — the default voice floor for every client. A
client's specific rules (below, if any) override anything here they conflict with, but
absent an override, follow all of this:

1. No throat-clearing openers. Cut any opening sentence that could start literally any
   post on any topic (e.g. "In today's fast-paced world..."). Start with the actual claim,
   the number, or the contrarian hook.
2. No rhetorical-question openers used as a crutch. One sharp, deliberate rhetorical
   question elsewhere in a post is fine; opening every post with one is the tell.
3. No hedge-phrases: "it's important to note," "it's worth mentioning," "one could argue,"
   "generally speaking." State the claim directly instead.
4. No rule-of-three list cadence in every paragraph. Vary rhythm — sometimes one point,
   sometimes five, sometimes a single blunt sentence with no list at all.
5. No formal transition words in casual copy: "moreover," "furthermore," "additionally,"
   "in conclusion." Use "and," "but," "so," or just start the next sentence.
6. No em-dash or semicolon overuse. One em dash for a genuine interruption is fine; three
   per post reads like a template. Semicolons almost never belong in social copy.
7. No engagement-bait closers ("What do you think? Let me know in the comments!",
   "Agree or disagree?"). End on the claim itself or a specific next step.
8. Concrete numbers beat vague intensifiers ("took close rate from 12% to 19%," not
   "significantly improved results") — but never invent a stat that isn't in the source
   transcript. Specificity is only good when it's real.
9. One idea, one thread. If using a metaphor or analogy, pick one image and carry it the
   whole way through instead of stacking multiple comparisons in the same post.
10. Contractions and sentence fragments are allowed and encouraged. Real voice breaks
    grammar rules on purpose — a one-word sentence as a beat, a fragment as a closer. Don't
    smooth these out into complete, correct sentences.'''

DEFAULT_BASE_RULES = '''Rules you never break:
- Never start a post with the word "I" as the very first word (unless the client's own rules or reference examples above explicitly show this as a wanted pattern -- then follow the client's lead)
- Never use: "game-changer", "dive in", "delve", "foster", "leverage", "in today's world", "it's important to", "revolutionize", "landscape", "unleash", "journey", "passionate", "thrilled to share", or any other AI cliche
- Never write hollow filler sentences that say nothing
- Never use bullet points unless the speaker explicitly listed items in the transcript
- End with either a strong closing line OR a single genuine question, never both (unless the client's own rules or reference examples above call for a different closing format, e.g. a comment-to-connect CTA -- then follow the client's lead)
- Hashtags: 3 maximum, only if genuinely relevant, placed at the very end on their own line
- Match the speaker's actual vocabulary, rhythm, and personality as heard in the transcript
- Write from the speaker's perspective in first person
- Every sentence should either advance the idea, deepen it, or land it. Nothing else.'''


def render_tone_profile_for_prompt(profile_dict):
    """Turn a stored Tone Profile JSON dict into a prompt-ready instruction
    block. Called by build_system_prompt/build_review_system_prompt when a
    client has an active profile (Phase 2, Ben's ask 2026-08-27).

    Filtering rules -- kept explicit so it's easy to see why a rendered
    profile is short:
      * summary and voice_do/voice_dont are always included when present.
      * category rows only render if score >= 40 (below that, telling the
        model about a trait that's basically absent is noise).
      * category rows with confidence < 40 render as soft "tendency"
        language ("this speaker tends to...") rather than assertions.
      * category rows with confidence >= 70 render as hard voice rules.
    """
    if not profile_dict or not isinstance(profile_dict, dict):
        return ''

    parts = ['ACTIVE TONE PROFILE — this replaces any generic style preset for this client. Follow it exactly.\n']

    summary = (profile_dict.get('summary') or '').strip()
    if summary:
        parts.append(f'Voice summary: {summary}')

    voice_do = profile_dict.get('voice_do') or []
    if voice_do:
        parts.append('\nTHIS VOICE DOES (do all of these):')
        for item in voice_do:
            parts.append(f'  - {item}')

    voice_dont = profile_dict.get('voice_dont') or []
    if voice_dont:
        parts.append('\nTHIS VOICE AVOIDS (never do any of these):')
        for item in voice_dont:
            parts.append(f'  - {item}')

    strong_lines = []
    tendency_lines = []
    for cat in TONE_PROFILE_CATEGORIES:
        c = profile_dict.get(cat)
        if not isinstance(c, dict):
            continue
        try:
            score = int(c.get('score', 0))
            confidence = int(c.get('confidence', 0))
        except (TypeError, ValueError):
            continue
        if score < 40:
            continue
        note = (c.get('note') or '').strip()
        if not note:
            continue
        cat_label = cat.replace('_', ' ')
        if confidence >= 70:
            strong_lines.append(f'  - {cat_label} ({score}/100): {note}')
        elif confidence >= 40:
            tendency_lines.append(f'  - {cat_label} ({score}/100, moderate confidence): {note}')
        else:
            tendency_lines.append(f'  - {cat_label} ({score}/100, low confidence -- tendency only): {note}')

    if strong_lines:
        parts.append('\nHIGH-CONFIDENCE VOICE TRAITS (treat as rules):')
        parts.extend(strong_lines)
    if tendency_lines:
        parts.append('\nOBSERVED TENDENCIES (weight, but do not force):')
        parts.extend(tendency_lines)

    return '\n'.join(parts) + '\n\n'


def build_system_prompt(style, client_rules, global_style_doc=None, base_rules=None, active_tone_profile=None):
    # A client with a real voice guide on file (style_rules and/or reference
    # copy) should be governed by that guide alone, not a generic preset
    # running in parallel. Found in production 2026-08-20: the "punchy" preset
    # (short, hard-stop sentences) directly fought Harris Projects' own rules
    # ("loose... sentences that could verge on run-on"), and BASE_RULES' "never
    # start with I" directly fought an intro pattern Harris's own rules called
    # for. The preset stays as a sensible default ONLY for clients who haven't
    # been given real rules yet.
    #
    # global_style_doc/base_rules are the live, editable values from the
    # global_style table (app.py fetches these and passes them in). They
    # default to the hardcoded originals so any caller that doesn't know
    # about global_style (existing tests, for instance) still works.
    global_style_doc = global_style_doc if global_style_doc is not None else DEFAULT_GLOBAL_STYLE_DOC
    base_rules = base_rules if base_rules is not None else DEFAULT_BASE_RULES

    # Phase 2 precedence (Ben's ask 2026-08-27): when an active Tone Profile
    # exists, it FULLY REPLACES the manual style_rules/reference-copy layer,
    # so a bad profile can't be silently rescued by an old rule that
    # accidentally still applies -- makes the profile's real signal
    # unambiguous when we validate against Harris Projects's 9 client-edit
    # pairs in Phase 3. Global style + base rules stay unconditionally
    # (those are house standards, not client voice). The old style_rules
    # code path is preserved verbatim for clients with no active profile.
    profile_block = ''
    if active_tone_profile:
        profile_block = render_tone_profile_for_prompt(active_tone_profile)
    has_active_profile = bool(profile_block)
    has_custom_voice = bool(client_rules and client_rules.strip())

    base = (
        'You are an elite ghostwriter specializing in LinkedIn content for business leaders, '
        'entrepreneurs, and subject matter experts. Your singular obsession is quality: posts that '
        'feel completely human, never AI-generated, never generic.\n\n'
    )
    # Skip the generic preset when EITHER the profile or manual style_rules
    # is in play -- both are client-specific voice guidance that shouldn't
    # be diluted by a generic preset running in parallel.
    if not has_active_profile and not has_custom_voice:
        base += f'{STYLE_PROMPTS.get(style, STYLE_PROMPTS["thought-leader"])}\n\n'

    base += f'{global_style_doc}\n\n'

    if has_active_profile:
        base += profile_block
        base += (
            'The Tone Profile above takes priority over the base rules below. If a base rule '
            'below conflicts with the Tone Profile, the profile wins -- do not enforce the base '
            'rule in that case.\n\n'
        )
    elif has_custom_voice:
        base += (
            'CLIENT-SPECIFIC RULES — read these carefully before writing anything. '
            'These take priority over EVERYTHING else in this prompt, including the base rules '
            'below. If a base rule below conflicts with a client rule or a client reference '
            'example, the client rule wins -- do not apply the base rule in that case. Follow '
            'every client instruction exactly:\n\n'
            f'{client_rules.strip()}\n\n'
        )
    base += base_rules
    return base


def build_user_prompt(title, section_body, full_corpus, length, style_docs_text, batch_context, client_rules=''):
    prompt = (
        'FULL TRANSCRIPT CORPUS: Read this to understand how this speaker communicates. '
        'Do not pull content from other videos for this post.\n\n'
        '---\n'
        f'{full_corpus[:8000]}\n'
        '---'
    )

    if style_docs_text and style_docs_text.strip():
        prompt += (
            '\n\nREFERENCE COPY — past writing samples from this client. Study the vocabulary, '
            'sentence rhythm, and voice. Do not copy content from these, only learn the style:\n\n'
            '---\n'
            f'{style_docs_text[:6000]}\n'
            '---'
        )

    if batch_context and batch_context.strip():
        prompt += (
            '\n\nCONTEXT FOR THIS SPECIFIC BATCH — background the writer should know about why '
            'these posts are being written right now (e.g. a campaign, an announcement, timing). '
            'Use this to inform tone and emphasis, but do not state it outright unless it '
            'naturally fits:\n\n'
            '---\n'
            f'{batch_context.strip()[:2000]}\n'
            '---'
        )

    prompt += (
        f'\n\nVIDEO SECTION TO WRITE ABOUT: {title}\n\n'
        '---\n'
        f'{section_body[:3500]}\n'
        '---\n\n'
        f'{LENGTH_INSTRUCTIONS.get(length, LENGTH_INSTRUCTIONS["medium"])}\n\n'
    )

    if client_rules and client_rules.strip():
        prompt += (
            f'REMINDER — before you write, re-read the client-specific rules in the system prompt '
            f'and make sure every single one is followed in this post.\n\n'
        )

    prompt += (
        'Write one LinkedIn post based solely on this video section. '
        'Output only the finished post with no preamble or explanation.'
    )

    return prompt


def build_review_system_prompt(style, client_rules, global_style_doc=None, base_rules=None, active_tone_profile=None):
    # Same precedence fix as build_system_prompt above -- the review pass has
    # to defer to the client's voice guide the same way the draft pass does,
    # or it will "correct" a draft back into violating the client's own rules.
    # Phase 2 adds the same Tone Profile precedence as the draft prompt --
    # when a profile is active it replaces the manual style_rules layer here
    # too, or the reviewer will "correct" a profile-conformant draft into
    # violating the profile.
    global_style_doc = global_style_doc if global_style_doc is not None else DEFAULT_GLOBAL_STYLE_DOC
    base_rules = base_rules if base_rules is not None else DEFAULT_BASE_RULES

    profile_block = ''
    if active_tone_profile:
        profile_block = render_tone_profile_for_prompt(active_tone_profile)
    has_active_profile = bool(profile_block)
    has_custom_voice = bool(client_rules and client_rules.strip())

    parts = (
        'You are a meticulous style and voice editor for LinkedIn content. You will be shown a '
        'draft post and the exact standards it was supposed to follow. Your only job is to check '
        'the draft against those standards and fix any violations.\n\n'
    )
    if not has_active_profile and not has_custom_voice:
        parts += f'{STYLE_PROMPTS.get(style, STYLE_PROMPTS["thought-leader"])}\n\n'

    parts += f'{global_style_doc}\n\n'

    if has_active_profile:
        parts += profile_block
        parts += (
            'The Tone Profile above takes priority over the base rules below. If a base rule '
            'conflicts with the Tone Profile, the profile wins -- do not "fix" a draft that '
            'complies with the profile just because it violates a base rule. Check the draft '
            'against every element of the profile and every base rule that does not conflict.\n\n'
        )
    elif has_custom_voice:
        parts += (
            'CLIENT-SPECIFIC RULES — these take priority over EVERYTHING else, including the base '
            'rules below. If a base rule conflicts with a client rule or a client reference '
            f'example, the client rule wins -- do not enforce the base rule in that case. Check '
            f'the draft against every one of these:\n\n{client_rules.strip()}\n\n'
        )

    parts += (
        base_rules
        + '\n\nIMPORTANT: Do not add, remove, or change any facts, claims, numbers, or substantive '
        'content from the draft — the underlying point and story must stay exactly the same. Only '
        'fix violations of the style/voice standards above (banned phrases, cliches, wrong openers, '
        'wrong closers, formatting issues, tone drift, etc). If the draft already fully complies, '
        'return it completely unchanged. Output ONLY the final post text, with no preamble, no '
        'explanation, and no notes about what you changed.'
    )
    return parts


def build_review_user_prompt(draft, style_docs_text):
    prompt = ''
    if style_docs_text and style_docs_text.strip():
        prompt += (
            'REFERENCE COPY — past writing samples from this client, for comparing voice/vocabulary:\n\n'
            '---\n'
            f'{style_docs_text[:6000]}\n'
            '---\n\n'
        )
    prompt += (
        'DRAFT POST TO REVIEW:\n\n'
        '---\n'
        f'{draft}\n'
        '---\n\n'
        'Check this draft against every standard in the system prompt. Rewrite only what violates '
        'them. Output only the final post text.'
    )
    return prompt


# ---------------------------------------------------------------------------
# Tone Profile system (Ben's ask, 2026-08-27).
#
# Phase 1: given either a raw transcript (30-90 min interview, "spoken") or
# 10-15 previous posts ("written"), produce a structured JSON profile that
# describes the voice across many dimensions. Every category carries a
# CONFIDENCE value based on source volume -- three posts don't get to speak
# for a whole voice the way 90 minutes of transcript can. Every score is
# backed by a supporting_quote pulled directly from the source, so the
# profile is auditable rather than an opaque set of numbers.
#
# The profile is INERT in Phase 1 -- it's stored but doesn't touch the
# actual generation pipeline yet. That's Phase 2. Phase 3 adds the Delta
# Analyzer that updates the profile based on client edits.
# ---------------------------------------------------------------------------

TONE_PROFILE_CATEGORIES = [
    # Emotional register
    'joy', 'confidence', 'vulnerability', 'humor', 'contrarianism',
    # Rhetorical devices
    'rhetoric', 'metaphor', 'question_usage', 'conjecture',
    # Structure & pacing
    'pace', 'sentence_length_variance', 'paragraph_rhythm', 'list_usage',
    # Substance
    'directness', 'concreteness', 'formality',
    # Signature patterns
    'opener_pattern', 'closer_pattern', 'signature_quirks',
]


def build_tone_profile_prompt(source_type, source_text, context='default'):
    """Build the system + user prompt pair for generating a tone profile v1
    from either a transcript or a set of previous posts.

    source_type: 'transcript' (spoken) or 'posts' (written). Affects how the
        prompt frames the analysis -- 'ums' are normal in one and diagnostic
        in the other.
    context: 'default', 'event', 'podcast', 'founder-profile', etc. Passed
        through so the profile can be labeled; doesn't currently change the
        prompt (all contexts share the same category list for now).
    """
    if source_type == 'transcript':
        material_label = 'raw interview transcript (spoken material -- expect "ums", repetition, meandering)'
        source_note = (
            'This is how the person TALKS. Some traits transfer to writing '
            '(word choice, worldview, humor); some don\'t (filler words, false '
            'starts, verbal tics). Note which is which where relevant.'
        )
    else:
        material_label = 'set of previous posts written by the person (written material -- final, polished output)'
        source_note = (
            'This is how the person WRITES. Every structural, punctuation, and '
            'rhythm choice is deliberate. Sentence-length variance and paragraph '
            'rhythm are especially trustworthy here.'
        )

    categories_block = ', '.join(TONE_PROFILE_CATEGORIES)

    system = (
        'You are a voice analyst. You will be given source material from a single '
        'person and must produce a structured Tone Profile describing that person\'s '
        'voice across many dimensions. Your output MUST be valid JSON only -- no '
        'preamble, no markdown fences, no trailing commentary.\n\n'
        f'The categories you MUST include (all of them, exact keys, in this order): {categories_block}\n\n'
        'For each category, output an object with:\n'
        '  - "score": integer 0-100 (0 = this trait is absent, 100 = extremely dominant)\n'
        '  - "confidence": integer 0-100 (how much the SOURCE MATERIAL VOLUME supports '
        'this reading -- 90 minutes of transcript = high confidence; 3 short posts = low)\n'
        '  - "note": one short sentence describing what you observed (plain language, no jargon)\n'
        '  - "supporting_quote": a direct quote from the source that supports the score '
        '(exact text, under 200 chars). Use empty string ONLY if the trait is entirely absent.\n\n'
        'Alongside the categories, include a top-level "summary" (2-3 sentence plain-language '
        'description of the voice) and a "voice_do" list (3-6 concrete things the voice DOES) '
        'and a "voice_dont" list (3-6 concrete things the voice AVOIDS or never does).\n\n'
        'Be specific. "Confident" is not a useful note; "makes strong claims without hedging, '
        'even when discussing contested topics" is. "Uses metaphor" is not useful; "reaches for '
        'construction and building metaphors specifically when discussing team dynamics" is.\n\n'
        'Confidence scoring rules (be honest, not generous):\n'
        '  - Under ~1000 chars of source: confidence must be <=40 for every category.\n'
        '  - 1000-5000 chars: confidence 40-70 range is appropriate.\n'
        '  - Over 5000 chars: confidence can go 70-95, but never 100 -- voices always have '
        'edge cases you haven\'t seen.\n\n'
        f'{source_note}'
    )

    user = (
        f'SOURCE MATERIAL ({material_label}), context label "{context}":\n\n'
        '---\n'
        f'{source_text[:60000]}\n'
        '---\n\n'
        'Produce the Tone Profile JSON now. Output ONLY the JSON object, nothing else.'
    )

    return system, user


def build_tone_profile_change_summary_prompt(old_profile_json, new_profile_json):
    """Given two profile JSONs, produce a short plain-language description of
    what changed and why it might matter. Used to populate the change_summary
    field so Ben can eyeball a version diff without staring at raw JSON."""
    system = (
        'You compare two Tone Profile JSON objects and describe what changed in plain language. '
        'Focus on category scores that moved by more than 10 points, and any voice_do / voice_dont '
        'items that were added or removed. Output ONLY 2-4 short sentences, no lists, no preamble. '
        'If nothing meaningful changed, say so bluntly.'
    )
    user = (
        f'OLD PROFILE:\n{old_profile_json}\n\n---\n\nNEW PROFILE:\n{new_profile_json}\n\n'
        'Describe what changed in 2-4 sentences.'
    )
    return system, user


def split_transcript(text):
    """Parse Degas transcript format: 'VIDEO: 01 - Title.mp4'"""
    sections = []
    title = None
    body_lines = []

    for raw_line in text.split('\n'):
        line = raw_line.strip()

        if 'VIDEO:' in line:
            if title and body_lines:
                sections.append({'title': title, 'body': ' '.join(body_lines)})
            m = re.search(r'VIDEO:\s*\d+\s*[-–]\s*(.+?)(?:\.mp4|\.mov|\.m4v)?\s*$', line, re.IGNORECASE)
            title = m.group(1).strip() if m else line
            body_lines = []
            continue

        if re.match(r'^[-=─]{3,}$', line):
            continue
        if re.match(r'^\[\d', line) and line.endswith(']'):
            continue
        if not line:
            continue

        body_lines.append(line)

    if title and body_lines:
        sections.append({'title': title, 'body': ' '.join(body_lines)})

    return sections


def split_transcript_plain(text):
    """Parse plain-text input, no Degas timestamps/VIDEO headers required
    (Ben's ask, 2026-08-24: "type in posts I want it to write without all
    the timestamps details"). Format is one block per post, each starting
    with a 'Post N:' line:

        Post 1:
        This is a post that I want you to write.

        Post 2:
        This is another post I want you to write.

    Content on the same line as 'Post N:' is kept too, so 'Post 1: Do the
    thing' works the same as putting the text on the next line. Each block's
    title becomes 'Post N' -- there's no separate title concept in this
    format, unlike split_transcript()'s VIDEO header titles."""
    sections = []
    title = None
    body_lines = []

    for raw_line in text.split('\n'):
        line = raw_line.strip()

        m = re.match(r'^Post\s+(\d+)\s*:\s*(.*)$', line, re.IGNORECASE)
        if m:
            if title and body_lines:
                sections.append({'title': title, 'body': ' '.join(body_lines)})
            title = f'Post {m.group(1)}'
            inline = m.group(2).strip()
            body_lines = [inline] if inline else []
            continue

        if not line:
            continue

        body_lines.append(line)

    if title and body_lines:
        sections.append({'title': title, 'body': ' '.join(body_lines)})

    return sections
