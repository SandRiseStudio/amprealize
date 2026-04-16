---
title: "Tokens & Tokenization"
type: concept
difficulty: beginner
prerequisites: []
tags:
  - nlp
  - fundamentals
last_updated: "2026-04-09"
sources:
  - "https://huggingface.co/docs/transformers/tokenizer_summary"
amprealize_relevance: "All LLM interactions in Amprealize begin with tokenization — understanding token budgets is essential for context composition and prompt engineering."
visibility: public
---

# Tokens & Tokenization

## Why This Matters

Every time you send text to an LLM, the first thing that happens is **tokenization** — the text gets chopped into small pieces called tokens. Think of it like how a sentence gets broken into words, except tokens aren't always neat words.

## The Intuition

Imagine you're packing a suitcase (the LLM's context window). You can't just throw in whole paragraphs — you need to fold everything into standard-sized pieces first. Tokenization is that folding process. Common words like "the" get a single token, while rare words like "amprealize" might need 3-4 tokens.

## How It Works

1. **Byte-Pair Encoding (BPE)**: The most common approach. Starts with individual characters, then iteratively merges the most frequent pairs. "running" might become `["run", "ning"]`.

2. **WordPiece**: Used by BERT. Similar to BPE but uses likelihood instead of frequency for merging.

3. **SentencePiece**: Language-agnostic. Works directly on raw text without pre-tokenization.

## Key Numbers to Know

| Model | Vocabulary Size | Context Window |
|-------|----------------|----------------|
| GPT-4 | ~100,000 tokens | 128K tokens |
| Claude | ~100,000 tokens | 200K tokens |
| Llama 3 | ~128,000 tokens | 128K tokens |

**Rule of thumb**: 1 token ≈ 4 characters in English, or about ¾ of a word.

## Why Token Count Matters

- **Cost**: LLM APIs charge per token (input + output)
- **Context window**: You can only fit so many tokens before the model forgets
- **Speed**: More tokens = longer generation time

## See Also

- [Embeddings](embeddings.md) — What happens after tokenization
- [Prompt Engineering](prompt-engineering.md) — Working within token budgets
