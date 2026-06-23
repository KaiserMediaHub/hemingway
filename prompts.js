const STYLE_PROMPTS = {
  'thought-leader': `You write in the style of a confident LinkedIn thought leader. Your writing is authoritative, direct, and opinionated. You make strong claims backed by experience. You use short punchy sentences mixed with deeper insight. You never hedge unnecessarily. You write like someone who has earned their perspective and is not afraid to share it. No buzzwords. No fluff. No AI-sounding phrases.`,
  'conversational': `You write in a warm, conversational tone like a smart, thoughtful person talking directly to a colleague or friend. You write in first person. You use natural language, occasional sentence fragments, and real human rhythm. You are never formal. You are never stiff. You write the way a confident person actually talks.`,
  'storyteller': `You write like a skilled storyteller. You open with a scene, a moment, or an observation that hooks the reader immediately. You build narrative momentum. You make the reader feel like they are there. You find the human truth in whatever the speaker said and lead with that. Your writing has texture, emotion, and forward pull.`,
  'punchy': `You write with extreme economy. Short sentences. Hard stops. No filler words. No throat-clearing. Every line must earn its place. You write like someone who respects the reader's time. High contrast between big ideas and simple language. No jargon. No padding. Think: a journalist who got paid by the cut, not the word.`
};

const LENGTH_INSTRUCTIONS = {
  'short': 'Write a short post of 3 to 5 focused paragraphs. Get in, say the thing, get out. Every word must be there for a reason.',
  'medium': 'Write a medium-length post of 5 to 8 paragraphs. Develop the idea with enough depth to be genuinely memorable.',
  'long': 'Write a longer post of 8 or more paragraphs. Develop the full narrative arc with supporting detail, texture, and a strong close.'
};

const BASE_RULES = `Rules you never break:
- Never start a post with the word "I" as the very first word
- Never use: "game-changer", "dive in", "delve", "foster", "leverage", "in today's world", "it's important to", "revolutionize", "landscape", "unleash", "journey", "passionate", "thrilled to share", or any other AI cliche
- Never write hollow filler sentences that say nothing
- Never use bullet points unless the speaker explicitly listed items in the transcript
- End with either a strong closing line OR a single genuine question, never both
- Hashtags: 3 maximum, only if genuinely relevant, placed at the very end on their own line
- Match the speaker's actual vocabulary, rhythm, and personality as heard in the transcript
- Write from the speaker's perspective in first person
- Every sentence should either advance the idea, deepen it, or land it. Nothing else.`;

function buildSystemPrompt(style, clientRules) {
  let prompt = `You are an elite ghostwriter specializing in LinkedIn content for business leaders, entrepreneurs, and subject matter experts. Your singular obsession is quality: posts that feel completely human, never AI-generated, never generic.

${STYLE_PROMPTS[style] || STYLE_PROMPTS['thought-leader']}

${BASE_RULES}`;

  if (clientRules && clientRules.trim()) {
    prompt += `\n\nADDITIONAL CLIENT-SPECIFIC RULES — these override or add to the rules above. Follow them exactly:\n${clientRules.trim()}`;
  }

  return prompt;
}

function buildUserPrompt(title, sectionBody, fullCorpus, length, styleDocsText, batchContext) {
  let prompt = `FULL TRANSCRIPT CORPUS: Read this to understand how this speaker communicates. Do not pull content from other videos for this post.

---
${fullCorpus.substring(0, 8000)}
---`;

  if (styleDocsText && styleDocsText.trim()) {
    prompt += `\n\nREFERENCE COPY — past writing samples from this client. Study the vocabulary, sentence rhythm, and voice. Do not copy content from these, only learn the style:

---
${styleDocsText.substring(0, 6000)}
---`;
  }

  if (batchContext && batchContext.trim()) {
    prompt += `\n\nCONTEXT FOR THIS SPECIFIC BATCH — background the writer should know about why these posts are being written right now (e.g. a campaign, an announcement, timing). Use this to inform tone and emphasis, but do not state it outright unless it naturally fits:

---
${batchContext.trim().substring(0, 2000)}
---`;
  }

  prompt += `\n\nVIDEO SECTION TO WRITE ABOUT: ${title}

---
${sectionBody.substring(0, 3500)}
---

${LENGTH_INSTRUCTIONS[length] || LENGTH_INSTRUCTIONS['medium']}

Write one LinkedIn post based solely on this video section. Output only the finished post with no preamble or explanation.`;

  return prompt;
}

// Parses Degas transcript format: "VIDEO: 01 - Title.mp4"
function splitTranscript(text) {
  const sections = [];
  const lines = text.split('\n');
  let title = null;
  let bodyLines = [];

  for (const rawLine of lines) {
    const line = rawLine.trim();

    if (line.includes('VIDEO:')) {
      if (title && bodyLines.length > 0) {
        sections.push({ title, body: bodyLines.join(' ') });
      }
      const m = line.match(/VIDEO:\s*\d+\s*[-\u2013]\s*(.+?)(?:\.mp4|\.mov|\.m4v)?\s*$/i);
      title = m ? m[1].trim() : line;
      bodyLines = [];
      continue;
    }

    if (/^[-=\u2500]{3,}$/.test(line)) continue;
    if (/^\[\d/.test(line) && line.endsWith(']')) continue;
    if (!line) continue;

    bodyLines.push(line);
  }

  if (title && bodyLines.length > 0) {
    sections.push({ title, body: bodyLines.join(' ') });
  }

  return sections;
}

module.exports = { buildSystemPrompt, buildUserPrompt, splitTranscript, STYLE_PROMPTS, LENGTH_INSTRUCTIONS };
