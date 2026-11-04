#!/usr/bin/env node
// sticker_intent.mjs — Shared lightweight intent classification (2026-11-03)
// Used by BOTH main chat and QQ. Same rules, no divergence.
//
// Returns: 'direct' | 'skip' | 'auto'
// - direct: explicit send request (e.g. "发表情包", "发个表情包，不要文字")
// - skip: explicit don't-send OR [Codex调试]/［Codex调试］ prefix
// - auto: everything else, INCLUDING "为什么不发", "现在呢", "你坏"
//
// "发个表情包，不要文字" → direct (negation targets text, not sticker)

const DEBUG_PREFIXES = ["[Codex调试]", "［Codex调试］"];

// Explicit SEND patterns
const SEND_PATTERNS = [
  /(发|发送|来)(一张|一个|张|个)?(表情包|表情)/,
  /(给我|看看).*(表情包|表情)/,
  /发表情包/, /发送表情包/, /来个表情包/, /来张.*表情包/,
];

// Explicit DON'T-SEND patterns (negation targets sticker action only)
const SKIP_PATTERNS = [
  /(不要|不用|别)(给我)?(发|发送)(送)?(一张|一个|张|个)?(表情包|表情|图|sticker)/,
];

export function classifyIntent(text) {
  if (!text || typeof text !== "string") return "auto";
  const t = text.trim();

  // 1. Debug prefix → skip (both half-width and full-width)
  for (const p of DEBUG_PREFIXES) {
    if (t.startsWith(p)) return "skip";
  }

  let mode = "auto";
  for (const raw of t.split(/[，,。！？!?；;\n]+/)) {
    const clause = raw.trim();
    // Asking about past behavior is not a new direct image request.
    if (/^(?:为什么|怎么|咋|解释|说说|你为什么|你怎么|你咋|是否|是不是|有没有|会不会)/.test(clause)) continue;
    if (/(?:不要|不用|别|不许)(?:再)?(?:给我)?(?:发|发送)(?:送)?[^，,。！？!?；;\n]{0,18}(?:表情包|表情|图片|图|sticker)/i.test(clause) ||
        /^(?:(?:这次|这条|现在|本轮|先|你|请)\s*)*(?:别|不要|不用)(?:再)?发(?:送)?(?:了|吧|啦)?$/.test(clause) ||
        /^(?:这次|这条|本轮)?(?:不要|不用)(?:表情包|表情|图片|图)$/.test(clause)) {
      mode = "skip";
      continue;
    }
    const lead = "(?:(?:请|麻烦|现在|这次|赶快|快|再|也|只|给我|帮我|你给我|你|能不能|可以|能否|可不可以|我要你|我想让你|我想要|我要|想要)\\s*)*";
    const send = new RegExp("^" + lead + "(?:发(?:送)?|来|给我看看|让我看看|看看)[^，,。！？!?；;\\n]{0,24}(?:表情包|表情|图片|图|sticker)", "i");
    if (send.test(clause)) mode = "direct";
  }
  return mode;
}

export function isValidMode(mode) {
  return mode === "auto" || mode === "direct" || mode === "skip";
}
