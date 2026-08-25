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

GLOBAL_STYLE_DOC = '''GLOBAL STYLE STANDARDS — the default voice floor for every client. A
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

BASE_RULES = '''Rules you never break:
- Never start a post with the word "I" as the very first word (unless the client's own rules or reference examples above explicitly show this as a wanted pattern -- then follow the client's lead)
- Never use: "game-changer", "dive in", "delve", "foster", "leverage", "in today's world", "it's important to", "revolutionize", "landscape", "unleash", "journey", "passionate", "thrilled to share", or any other AI cliche
- Never write hollow filler sentences that say nothing
- Never use bullet points unless the speaker explicitly listed items in the transcript
- End with either a strong closing line OR a single genuine question, never both (unless the client's own rules or reference examples above call for a different closing format, e.g. a comment-to-connect CTA -- then follow the client's lead)
- Hashtags: 3 maximum, only if genuinely relevant, placed at the very end on their own line
- Match the speaker's actual vocabulary, rhythm, and personality as heard in the transcript
- Write from the speaker's perspective in first person
- Every sentence should either advance the idea, deepen it, or land it. Nothing else.'''


def build_system_prompt(style, client_rules):
    # A client with a real voice guide on file (style_rules and/or reference
    # copy) should be governed by that guide alone, not a generic preset
    # running in parallel. Found in production 2026-08-20: the "punchy" preset
    # (short, hard-stop sentences) directly fought Harris Projects' own rules
    # ("loose... sentences that could verge on run-on"), and BASE_RULES' "never
    # start with I" directly fought an intro pattern Harris's own rules called
    # for. The preset stays as a sensible default ONLY for clients who haven't
    # been given real rules yet.
    has_custom_voice = bool(client_rules and client_rules.strip())

    base = (
        'You are an elite ghostwriter specializing in LinkedIn content for business leaders, '
        'entrepreneurs, and subject matter experts. Your singular obsession is quality: posts that '
        'feel completely human, never AI-generated, never generic.\n\n'
    )
    if not has_custom_voice:
        base += f'{STYLE_PROMPTS.get(style, STYLE_PROMPTS["thought-leader"])}\n\n'

    base += f'{GLOBAL_STYLE_DOC}\n\n'

    if has_custom_voice:
        base += (
            'CLIENT-SPECIFIC RULES — read these carefully before writing anything. '
            'These take priority over EVERYTHING else in this prompt, including the base rules '
            'below. If a base rule below conflicts with a client rule or a client reference '
            'example, the client rule wins -- do not apply the base rule in that case. Follow '
            'every client instruction exactly:\n\n'
            f'{client_rules.strip()}\n\n'
        )
    base += BASE_RULES
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


def build_review_system_prompt(style, client_rules):
    # Same precedence fix as build_system_prompt above -- the review pass has
    # to defer to the client's voice guide the same way the draft pass does,
    # or it will "correct" a draft back into violating the client's own rules.
    has_custom_voice = bool(client_rules and client_rules.strip())

    parts = (
        'You are a meticulous style and voice editor for LinkedIn content. You will be shown a '
        'draft post and the exact standards it was supposed to follow. Your only job is to check '
        'the draft against those standards and fix any violations.\n\n'
    )
    if not has_custom_voice:
        parts += f'{STYLE_PROMPTS.get(style, STYLE_PROMPTS["thought-leader"])}\n\n'

    parts += f'{GLOBAL_STYLE_DOC}\n\n'

    if has_custom_voice:
        parts += (
            'CLIENT-SPECIFIC RULES — these take priority over EVERYTHING else, including the base '
            'rules below. If a base rule conflicts with a client rule or a client reference '
            f'example, the client rule wins -- do not enforce the base rule in that case. Check '
            f'the draft against every one of these:\n\n{client_rules.strip()}\n\n'
        )

    parts += (
        BASE_RULES
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
