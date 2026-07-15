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

BASE_RULES = '''Rules you never break:
- Never start a post with the word "I" as the very first word
- Never use: "game-changer", "dive in", "delve", "foster", "leverage", "in today's world", "it's important to", "revolutionize", "landscape", "unleash", "journey", "passionate", "thrilled to share", or any other AI cliche
- Never write hollow filler sentences that say nothing
- Never use bullet points unless the speaker explicitly listed items in the transcript
- End with either a strong closing line OR a single genuine question, never both
- Hashtags: 3 maximum, only if genuinely relevant, placed at the very end on their own line
- Match the speaker's actual vocabulary, rhythm, and personality as heard in the transcript
- Write from the speaker's perspective in first person
- Every sentence should either advance the idea, deepen it, or land it. Nothing else.'''


def build_system_prompt(style, client_rules):
    base = (
        'You are an elite ghostwriter specializing in LinkedIn content for business leaders, '
        'entrepreneurs, and subject matter experts. Your singular obsession is quality: posts that '
        'feel completely human, never AI-generated, never generic.\n\n'
        f'{STYLE_PROMPTS.get(style, STYLE_PROMPTS["thought-leader"])}\n\n'
    )
    if client_rules and client_rules.strip():
        base += (
            'CLIENT-SPECIFIC RULES — read these carefully before writing anything. '
            'These take priority over everything else. Follow every instruction exactly:\n\n'
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
