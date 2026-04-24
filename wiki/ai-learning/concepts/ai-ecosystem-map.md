---
title: "The AI Ecosystem Map: Labs, Models, Apps, Tools & Frameworks"
type: concept
difficulty: beginner
prerequisites: []
tags:
  - overview
  - ecosystem
  - models
  - tools
  - ides
  - frameworks
last_updated: 2026-04-23
sources:
  - "OpenAI — Introducing GPT-5.5 (April 2026): https://openai.com/index/introducing-gpt-5-5/"
  - "OpenAI API Models Reference: https://developers.openai.com/api/docs/models/all/"
  - "OpenAI ChatGPT Plans & Pricing: https://openai.com/pricing/"
  - "OpenAI — About ChatGPT Pro tiers: https://help.openai.com/en/articles/9793128-about-chatgpt-pro-plans"
  - "AI Toolbox — ChatGPT Models Explained 2026: https://www.ai-toolbox.co/chatgpt-models/chatgpt-models-explained-complete-comparison-2026"
  - "Anthropic — Plans & Pricing: https://www.anthropic.com/pricing"
  - "Anthropic Claude API Pricing: https://platform.claude.com/docs/en/about-claude/pricing"
  - "SSD Nodes — Claude Code Pricing 2026: https://www.ssdnodes.com/blog/claude-code-pricing-in-2026-every-plan-explained-pro-max-api-teams/"
  - "Google Gemini API Pricing: https://ai.google.dev/gemini-api/docs/pricing"
  - "GeminiPricing.com — Gemini Advanced: https://www.geminipricing.com/gemini-advanced"
  - "Finout — Gemini Pricing 2026: https://www.finout.io/blog/gemini-pricing-in-2026"
  - "Anthropic Claude model lineup: https://www.anthropic.com/claude"
  - "Anna Arteeva — A map of AI coding tools (March 2026): https://annaarteeva.medium.com/a-map-of-ai-coding-tools-ides-agents-all-in-on-app-builders-and-foundation-models-60a9b5f2ed80"
  - "NxCode — Best AI Coding Tools 2026: https://www.nxcode.io/resources/news/best-ai-for-coding-2026-complete-ranking"
  - "Nimbalyst — Best AI IDEs in 2026: https://nimbalyst.com/blog/best-ai-ides-2026/"
  - "iBuidl — AI Agent Frameworks in 2026: https://ibuidl.org/blog/ai-agent-frameworks-comparison-20260310"
  - "Kimi K2.5 — Awesome Agents: https://awesomeagents.ai/models/kimi-k2-5/"
  - "Build Fast With AI — Best AI Models April 2026: https://www.buildfastwithai.com/blogs/best-ai-models-april-2026"
  - "VibeCoding — Claude Code CLI vs Desktop 2026: https://vibecoding.app/blog/claude-code-cli-vs-desktop"
amprealize_relevance: "Orientation page for the team. Amprealize sits at the intersection of Layers 4–5: it is a developer tool (Layer 4) built with agentic framework patterns (Layer 5) that exposes MCP tools consumed by other tools in Layer 4."
visibility: public
---

# The AI Ecosystem Map

## Why This Is So Confusing

The same words get reused across completely different layers of the stack. "Claude" is a company, a model family, a chat app, a coding CLI, a desktop app, a VS Code extension, and a web product. "Copilot" means GitHub Copilot (an IDE extension), Microsoft Copilot (a chat app), and GitHub Copilot coding agent (an autonomous PR writer) — all from different teams.

This page gives every confusing term a precise home in a six-layer map. Once you know which layer a thing lives in, the naming makes sense.

```
Layer 1: AI Labs          — who trains the models
Layer 2: Foundation Models — the actual AI weights
Layer 3: Consumer Apps    — chat UIs for everyday use
Layer 4: Developer Tools  — coding IDEs, extensions, CLIs
Layer 5: Frameworks       — SDKs for building AI systems
Layer 6: Inference Infra  — where the model actually runs
```

---

## Layer 1 — AI Labs (Who Trains the Models)

These are the companies that spend billions training foundation models. A lab is not an app — it is the upstream source for the weights that power everything else.

| Lab | HQ | Known for | Flagship model (Apr 2026) |
|-----|----|-----------|--------------------------|
| **OpenAI** | US (Microsoft-backed) | ChatGPT, GPT family, Codex, DALL-E | GPT-5.5 |
| **Anthropic** | US (Amazon/Google-backed) | Claude family, Claude Code | Claude Opus 4.7 |
| **Google / Google DeepMind** | US | Gemini family, Gemma (open-weight) | Gemini 3.1 Pro |
| **Meta AI** | US (open-weight) | Llama family | Llama 4 Scout |
| **xAI** | US (Elon Musk) | Grok family | Grok 4.20 |
| **Mistral AI** | France | Mistral Large, open-weight small models | Mistral Large 3 |
| **Moonshot AI** | China | Kimi family (open-weight MoE) | Kimi K2.5 |
| **MiniMax** | China | MiniMax M-series | MiniMax M2.5 |
| **Zhipu AI / Z.ai** | China | GLM family (open-weight) | GLM-5 |
| **Alibaba** | China | Qwen family | Qwen 3.5 |
| **DeepSeek** | China (Lianxin-backed) | DeepSeek-V series (open-weight) | DeepSeek V4 |
| **Perplexity AI** | US | Sonar (search-grounded; built on Llama) | Sonar Pro |
| **Cohere** | Canada | Command family (enterprise focus) | Command R+ |

> **Key point:** Labs and models are not the same thing. Anthropic is the lab. Claude is the model. Claude.ai is the app. All three words get used interchangeably in conversation, which is where the confusion starts.

---

## Layer 2 — Foundation Models (The AI Brain)

A foundation model is a set of trained weights — not an app, not a service, not a chatbot. The same weights can power a chat interface, a coding CLI, a VS Code extension, and an API endpoint simultaneously.

> **Core insight:** GPT-5.4 is a model. ChatGPT is an app that *uses* GPT-5.4. Cursor is another app that *also uses* GPT-5.4. GitHub Copilot can use it too. The same underlying model, accessed through completely different surfaces.

### OpenAI GPT-5.x Family (as of April 23, 2026 — GPT-5.5 released today)

| Model | What it is | Context | API price (input) |
|-------|-----------|---------|-------------------|
| **GPT-5.5** | Latest flagship; best coding + agentic; rolling out to ChatGPT and Codex | 1M tokens | API coming soon |
| **GPT-5.4** | Current API flagship; powers most production apps | 1M tokens | $2.50/M tokens |
| **GPT-5.4 Pro** | Higher-quality variant of GPT-5.4 | 1M tokens | Premium |
| **GPT-5.4 mini** | Near-flagship performance, lower cost + latency | 400K tokens | $0.75/M tokens |
| **GPT-5.4 nano** | Cheapest GPT-5-class model for simple tasks | 400K tokens | $0.20/M tokens |
| **GPT-5.3-Codex** | Dedicated agentic coding variant; powers the Codex product | — | Codex-only |
| **Cursor Composer 2** | Cursor's own RL-trained coding model *(not OpenAI)* | — | Cursor-only |

### Anthropic Claude 4.x Family

| Model | What it is | Context | Best use |
|-------|-----------|---------|---------|
| **Claude Opus 4.7** | Latest GA (April 15, 2026); step-change agentic coding | 1M tokens | Complex multi-file coding, long-horizon tasks |
| **Claude Sonnet 4.6** | Speed/cost balance; most popular for production | 1M tokens (beta) | Everyday coding, high-volume production |
| **Claude Haiku 4.5** | Fast, cheap, high-volume tasks | — | Simple completions, rapid responses |

### Google Gemini 3.x Family

| Model | What it is | Context | Notes |
|-------|-----------|---------|-------|
| **Gemini 3.1 Pro** | Multimodal flagship; leads Artificial Analysis Intelligence Index | 1M tokens | Best breadth across benchmarks |
| **Gemini 3 Flash** | Default model in the Gemini app; fast balance | 1M tokens | Consumer app default |
| **Gemini 3.1 Flash-Lite** | Cheapest large-context option commercially available | 1M tokens | $0.25/M input |
| **Gemma 4 (31B)** | Open-weight; Apache 2.0; runs on-device | 256K tokens | #3 on Arena AI leaderboard |

### Other Notable Models (April 2026)

| Model | Lab | What makes it notable |
|-------|-----|----------------------|
| **Kimi K2.5** | Moonshot AI | 1T parameter MoE, open-weight (modified MIT); 256K context; agentic swarm (up to 100 sub-agents); $0.60/M input |
| **MiniMax M2.5** | MiniMax | 80.2% on SWE-bench Verified — matches best closed models; $0.30/M input |
| **Grok 4.20** | xAI | Runs 4 parallel agents internally; real-time X (Twitter) data access |
| **Llama 4 Scout** | Meta | 10M token context window; open-weight; Apache 2.0 |
| **DeepSeek V4** | DeepSeek | ~$0.28/M input; ~90% of GPT-5.4 quality; built on Huawei Ascend (no NVIDIA) |
| **GLM-5** | Zhipu / Z.ai | 77.8% SWE-bench; top open-source Chatbot Arena Elo; $3/month subscription tier |
| **Qwen 3.5 (9B)** | Alibaba | 9B model matching 120B+ models on reasoning; Apache 2.0 |

---

## Layer 3 — Consumer AI Apps (Chat for Everyday Use)

These are the products a non-technical person opens to talk to an AI. No coding, no API keys, no setup.

| App | Company | Primary model | Where you find it |
|-----|---------|---------------|--------------------|
| **ChatGPT** | OpenAI | GPT-5.x family | Web, iOS, Android, macOS/Windows desktop |
| **Claude.ai** | Anthropic | Claude Opus/Sonnet | Web, iOS, Android, macOS desktop |
| **Gemini** | Google | Gemini 3.x | Web, iOS, Android; baked into Google Workspace |
| **Microsoft Copilot** | Microsoft | GPT-5.x via Azure | Web, Windows, iOS, Android |
| **Grok** | xAI | Grok 4.x | Web, X (Twitter) app |
| **Perplexity** | Perplexity AI | Sonar (Llama-based) | Web, iOS, Android |
| **Kimi** | Moonshot AI | Kimi K2.5 | Web, iOS, Android |

> **These are all chatbots.** They differ in which model they use, what live data they can access (web, email, calendar), and what extra features they layer on top (image generation, voice mode, memory, etc.).

### Consumer App Subscription Plans (April 2026)

Consumer AI apps use **flat-rate subscription pricing** — you pay a fixed monthly fee for access to the app and its features, not per message sent. This is fundamentally different from API pricing (see Layer 6), where you pay per token consumed and get raw model access.

**OpenAI / ChatGPT**

| Plan | Price | Models included | Key features |
|------|-------|-----------------|--------------|
| **Free** | $0/mo | GPT-5.3 Instant (limited; ads in US) | Basic chat, web search, limited image gen |
| **Go** | $8/mo | GPT-5.3 + more volume, still has ads | More messages; missing advanced features |
| **Plus** | $20/mo | GPT-5.3 + GPT-5.4 Thinking | Deep Research (10/mo), Sora, Codex, Agent Mode |
| **Pro $100** | $100/mo | Everything in Plus | 5× higher limits than Plus |
| **Pro $200** | $200/mo | GPT-5.4 Pro | 20× Plus limits, 250 Deep Research runs/mo, double context window |
| **Business** | $25/user/mo | Unlimited GPT-5.4 + Thinking | 60+ integrations (Slack, Drive, GitHub), SOC 2, SAML SSO, team workspace |
| **Enterprise** | Custom | All models | Privately hosted AI, SCIM, audit logs, dedicated support |

**Anthropic / Claude.ai**

| Plan | Price | Models included | Key features |
|------|-------|-----------------|--------------|
| **Free** | $0/mo | Sonnet + Haiku | Basic chat; web, iOS, Android, desktop |
| **Pro** | $20/mo ($17 annual) | Opus + Sonnet + Haiku | Claude Code, Research, cross-conversation memory, ~5× more usage than Free |
| **Max 5×** | $100/mo | All models | 5× Pro usage, priority access, early features |
| **Max 20×** | $200/mo | All models | 20× Pro usage, highest output limits, parallel agent workflows |
| **Team (Standard)** | $25/seat/mo | All Max features | Admin controls, SSO, no training on data by default |
| **Team (Premium)** | $100/seat/mo | All models + Claude Code | 5× Standard usage; for developer-heavy teams |
| **Enterprise** | Custom | All models | 500K context window, HIPAA-ready, SCIM, audit logs, compliance API |

**Google / Gemini**

| Plan | Price | Models included | Key features |
|------|-------|-----------------|--------------|
| **Free** | $0/mo | Gemini Flash (lighter) | Basic chat; limited features |
| **Google AI Pro** | $19.99/mo | Gemini 2.5 Pro + Gemini 3 (US) | Deep Research, Veo video gen, Gemini in Gmail/Docs/Sheets, 1,000 AI credits/mo |
| **Google AI Ultra** | ~$41.67/mo ($124.99/3 months) | Gemini 3.1 Pro, all models | Highest limits, 25,000 AI credits/mo, $100/mo Google Cloud credits, YouTube Premium |

> **Subscription ≠ API access.** None of these consumer plans give you programmatic API access. If you want to call a model from your own code or product, you need a separate API account with pay-per-token billing — see Layer 6.

---

## Layer 4 — Developer / Coding Tools

This is where the naming chaos peaks. The same capability (an AI that reads and edits your code) comes packaged as four completely different form factors:

```
                    ┌─────────────────────────────────┐
                    │      Foundation Model            │
                    │  (GPT-5.5, Claude Opus 4.7, ...) │
                    └──┬──────┬──────────┬────────┬───┘
                       │      │          │        │
                  ┌────▼──┐ ┌─▼──────┐ ┌▼──────┐ ┌▼──────────┐
                  │AI-Native│ │IDE     │ │Terminal│ │Web/Desktop│
                  │IDE     │ │Extension│ │CLI    │ │Coding App │
                  │(new    │ │(add-on │ │(no GUI)│ │(GUI agent)│
                  │editor) │ │to your │ │       │ │           │
                  │        │ │editor) │ │       │ │           │
                  └────────┘ └────────┘ └───────┘ └───────────┘
```

### 4a — AI-Native IDEs (replaces your editor)

You install this *instead of* VS Code. It's a complete editor built from the ground up around AI.

| Tool | Built on | Models supported | Key differentiator |
|------|---------|------------------|--------------------|
| **Cursor** | VS Code fork | Claude, GPT-5.x, Gemini, Composer 2 | Best autocomplete (Supermaven); Composer multi-file editing; 1M+ users |
| **Windsurf** | Proprietary | Claude, GPT, Gemini | Flows agentic mode; beginner-friendly |
| **Zed** | Rust (native) | Multi-model | Fastest keystroke latency; strong local-model story |
| **Google Antigravity** | Proprietary | Gemini-first | Public preview; Manager view for agent oversight |
| **Trae** | Proprietary (ByteDance) | Multi-model | Growing fast; Asia-focused |
| **Kiro** | Proprietary (Amazon) | Amazon Nova | AWS-native; early access |

### 4b — IDE Extensions (adds AI to your existing editor)

You keep VS Code (or JetBrains, or Xcode) and install a plugin. Zero disruption to your current workflow.

| Extension | Company | Works in | Models |
|-----------|---------|---------|--------|
| **GitHub Copilot** | GitHub / Microsoft | VS Code, JetBrains, Xcode, Neovim, Eclipse, Vim | GPT-5.x, Claude, Gemini (your choice) |
| **Claude Code** (extension) | Anthropic | VS Code, JetBrains | Claude Sonnet / Opus |
| **Codex** (extension) | OpenAI | VS Code, Cursor, Windsurf | GPT-5.5 / GPT-5.4 |
| **Gemini Code Assist** | Google | VS Code, JetBrains | Gemini 3.1 Pro |
| **Amazon Q Developer** | AWS | VS Code, JetBrains | Amazon Nova |
| **Continue** | Open-source | VS Code, JetBrains | BYOK — any model you configure |

### 4c — Terminal / CLI Agents (lives in your terminal, no GUI)

You type a command in your terminal. The agent reads and writes your actual local files, runs shell commands, commits to git — all without any visual editor. Maximum control, steepest learning curve.

| Tool | Company | License | Key trait |
|------|---------|---------|-----------|
| **Claude Code CLI** | Anthropic | Proprietary | `claude` command; 80.8% SWE-bench Verified; 1M context; MCP support; CLAUDE.md memory files; the most capable terminal agent |
| **Codex CLI** | OpenAI | Open-source (MIT) | `codex` command; BYOK with any ChatGPT-compatible model; sandboxed execution |
| **Aider** | Open-source | Apache 2.0 | Git-native workflow; strong on refactoring; BYOK |
| **OpenCode** | Open-source | MIT | Multi-model BYOK; free (you pay for API only) |

### 4d — Web / Desktop Coding Agent Apps (GUI wrappers for agent workflows)

Dedicated apps for coding tasks — not general-purpose chat. They give you a visual interface to the same agent capability you'd run in the terminal.

| App | Company | Surface | What it is |
|-----|---------|---------|-----------|
| **Claude Code Desktop** | Anthropic | macOS app (Windows preview) | Visual diffs; Cowork background agents; Routines (scheduled automations); parallel sessions |
| **claude.ai/code** | Anthropic | Browser | Cloud-sandboxed Claude Code; GitHub repo cloning and integration |
| **Codex** (chatgpt.com/codex) | OpenAI | Browser | Web-based Codex coding agent; cloud task execution with approval workflow |

> **"Claude Code" is one brand name for four different surfaces:** CLI, VS Code extension, Desktop App, and web. They share the same Claude model and billing account but have very different UX and capability levels. The CLI is the most powerful (multi-agent, unlimited sessions, full MCP, full filesystem). The web version is the most restricted (cloud sandbox only).

---

## Layer 5 — Agentic Frameworks (SDKs for Building AI Systems)

These are developer libraries for engineering teams building AI-powered applications. They are not end-user tools.

If you are a developer writing Python or TypeScript to build the *next* Claude Code, Cursor, or an internal AI workflow — this is your layer.

| Framework | Who | Language | Best for | When to pick it |
|-----------|-----|----------|---------|----------------|
| **LangChain / LangGraph** | LangChain Inc. | Python, TypeScript | Complex stateful workflows; production systems | Needs state machines, checkpointing, human-in-the-loop (48K+ stars) |
| **CrewAI** | CrewAI Inc. | Python | Role-based multi-agent teams; rapid prototyping | Need a working multi-agent prototype fast |
| **AutoGen** (v0.4+) | Microsoft | Python, .NET | Conversational multi-agent debate / consensus | Agents need to negotiate or debate; enterprise .NET shops |
| **PydanticAI** | Pydantic team | Python | Type-safe production agents; FastAPI integration | New project where type safety and DI matter |
| **LlamaIndex** | LlamaIndex Inc. | Python | RAG + agentic workflows over large document sets | Document-heavy knowledge retrieval |
| **Semantic Kernel** | Microsoft | C#, Python, Java | Enterprise .NET / Azure integration | Microsoft stack; existing Azure identity |
| **Google ADK** | Google | Python | A2A-compatible agents on Google Cloud | Building agents that use A2A protocol |
| **OpenAI Agents SDK** | OpenAI | Python, TypeScript | Simple tool-calling agents using OpenAI models | OpenAI-first shop; want minimal abstraction |

> **You almost never need a framework if you are an end-user.** Frameworks are for the team building the product you will eventually use. If you are deciding between Cursor and GitHub Copilot, this layer is not relevant to you.

---

## Layer 6 — Inference Providers (Where the Model Actually Runs)

Inference providers are usually invisible to end users. They are the cloud services that actually host the model weights and serve the responses. A single lab may run its own inference (Anthropic API) or license to third-party providers (Mistral on Azure, Claude on Bedrock).

| Provider | What it offers |
|----------|----------------|
| **OpenAI API** | GPT-5.x models via REST; used by ChatGPT, Codex, and thousands of third-party apps |
| **Anthropic API** | Claude models; used by Claude.ai, Claude Code, and third-party apps |
| **Google AI Studio** | Gemini models for developers; free tier; easy API access |
| **Google Vertex AI** | Gemini + third-party models for enterprise; compliance, private networking |
| **AWS Bedrock** | Multi-provider (Claude, Llama, Mistral, Gemma) via AWS; enterprise compliance and IAM |
| **Azure OpenAI** | OpenAI models served through Microsoft's cloud; enterprise SLAs, data residency |
| **OpenRouter** | Aggregates 150+ models from all providers via a single API and unified billing |
| **Groq** | Ultra-fast inference (Llama, Mistral, Gemma) via custom LPU silicon; lowest latency |
| **Fireworks AI** | Fast open-model hosting; fine-tuning support |
| **Together AI** | Open-weight model hosting with fine-tuning and LoRA |
| **Ollama** | Run open-weight models (Llama, Mistral, Gemma, Qwen, etc.) entirely on your own hardware; no API key, no cloud, no cost per token |

### API Pricing: On-Demand Pay-Per-Token (April 2026)

APIs charge per million tokens (MTok) — **input** (your prompt) and **output** (the model's response) are billed separately. There is no subscription; you pay only for what you use. This makes APIs ideal for variable workloads, automation, and building products.

**OpenAI API**

| Model | Input (per 1M tokens) | Output (per 1M tokens) | Notes |
|-------|----------------------|------------------------|-------|
| GPT-5.4 | $2.50 | $10.00 | Current API flagship; 1M context |
| GPT-5.4 mini | $0.75 | ~$3.00 | Near-flagship performance at lower cost |
| GPT-5.4 nano | $0.20 | ~$0.80 | High-volume, simple tasks |
| GPT-5.5 | TBA | TBA | API availability announced soon |

**Anthropic API**

| Model | Input (per 1M tokens) | Output (per 1M tokens) | Notes |
|-------|----------------------|------------------------|-------|
| Claude Opus 4.7 | $5.00 | $25.00 | Latest flagship; 1M context |
| Claude Sonnet 4.6 | $3.00 | $15.00 | Most popular in production |
| Claude Haiku 4.5 | $1.00 | $5.00 | Fast, high-volume tasks |
| (Prompt caching) | 70–90% off | — | On repeated/cached context |

**Google Gemini API** (via AI Studio or Vertex AI)

| Model | Input (per 1M tokens) | Output (per 1M tokens) | Notes |
|-------|----------------------|------------------------|-------|
| Gemini 3.1 Pro | $2.00 / $4.00† | $12.00 / $18.00† | Most capable; context-tiered pricing |
| Gemini 2.5 Pro | $1.25 / $2.50† | $10.00 / $15.00† | Strong coding + reasoning |
| Gemini 3 Flash | $0.50 | $3.00 | Fast, balanced |
| Gemini 2.5 Flash-Lite | $0.10 | $0.40 | Cheapest large-context option |

†Lower price for prompts ≤200K tokens; higher for prompts >200K tokens.

> **Free API tiers:** Google AI Studio offers 25 Gemini 2.5 Pro requests/day and 1,500 Flash requests/day free — generous for development and testing. Anthropic gives new accounts small free credits. OpenAI has no free tier but has very cheap nano/mini models.

> **Subscription vs. API breakeven:** At heavy daily use (e.g., 8+ hours of Claude Code agentic work), the Claude Max 20× subscription at $200/month is typically cheaper than equivalent API token spend. For lighter, variable, or bursty usage, pay-as-you-go API is usually more cost-effective. Model your actual usage pattern before committing to either.

---

## Common Confusions, Resolved

### "Anthropic vs. Claude"
- **Anthropic** = the company (lab). Trains the models.
- **Claude** = the model family (Opus, Sonnet, Haiku). The weights.
- **Claude.ai** = the consumer chat app (Layer 3).
- **Claude Code** = the developer coding tool (Layer 4), which itself ships in four forms.

### "ChatGPT vs. GPT-5.4 vs. GPT-5.5"
- **GPT-5.4 / GPT-5.5** = models (Layer 2). The AI brain.
- **ChatGPT** = the consumer app (Layer 3) that uses GPT-5.x.
- Cursor, GitHub Copilot, and your custom app can also use the same GPT-5.4 model via the API.

### "ChatGPT (the app) vs. OpenAI API — same model, very different harness"

This is one of the most practically important distinctions to understand.

**Same model, completely different experience.** ChatGPT and the OpenAI API both use GPT-5.x weights — but ChatGPT wraps the model in a thick application layer ("harness") that adds features, enforces limits, and abstracts away control. The API gives you the raw model.

| What you get | ChatGPT (consumer app) | OpenAI API (developer access) |
|---|---|---|
| **Pricing model** | Flat-rate subscription (Free → $200/mo) | Pay-per-token; no monthly minimum |
| **Model selection** | Auto-routing router picks model for you; you can nudge it | You explicitly specify the model (`gpt-5.4`, `gpt-5.4-mini`, etc.) |
| **Context window** | Tiered by plan (~320 pages on Plus; ~680 on Pro $200) | Full per-model spec (1M tokens on GPT-5.4) |
| **Memory** | Built-in cross-conversation memory | None by default — you manage your own context |
| **Web browsing** | Built-in (Bing-powered) | Tool you add yourself |
| **Image generation** | Built-in (DALL-E) | Separate Images API call |
| **Code execution** | Built-in sandbox | Tool you add yourself |
| **Voice mode** | Built-in | Separate Realtime API |
| **System prompt** | Managed by OpenAI (you can't see it) | You write it; full control |
| **Tools / function calling** | Predefined by OpenAI | You define your own tools |
| **Data privacy** | Training opt-out varies by plan; conversation storage on OpenAI servers | No training on API data by default; you control retention |
| **Best for** | Individuals and teams doing knowledge work | Developers building products or automating workflows |

> **Key insight:** A developer paying $20/month for ChatGPT Plus and a developer paying $20 in API tokens are not getting the same thing. The Plus subscriber gets a polished product with baked-in tools and routing but less control. The API caller gets raw model access with full control but must build the tooling layer themselves. For many developer use cases, the API is actually *cheaper* per effective output — teams that switch from ChatGPT to the API often cut costs 30–50% by routing simpler tasks to cheaper models explicitly.

> **ChatGPT's auto-router:** Since early 2026, ChatGPT uses an automatic routing layer that picks between GPT-5.3 Instant and GPT-5.4 Thinking based on query complexity. You can override this by manually selecting a model, but the default is opaque. The API has no such routing — what you ask for is exactly what runs.

### "Claude Code CLI vs. Claude Code Desktop vs. Claude Code extension"
All three are branded "Claude Code." All use Claude models. They are very different:

| | CLI | Desktop App | VS Code Extension |
|-|-----|-------------|-------------------|
| Where it runs | Your terminal | macOS app (Win preview) | VS Code sidebar |
| File access | Full filesystem | Full local filesystem | Current workspace |
| Multiple sessions | Unlimited | Yes (new parallel design) | One per workspace |
| MCP support | Full | Partial | Yes |
| Best for | Power users, automation, overnight runs | Visual workflow, Cowork agents | Daily coding inside VS Code |

### "Codex vs. ChatGPT"
Both are OpenAI products. ChatGPT is a general-purpose assistant. Codex is specifically for autonomous coding tasks. GPT-5.3-Codex and GPT-5.5 are the *models* inside Codex. "Codex" by itself means the product/app (browser + CLI + extension).

### "Cursor vs. GitHub Copilot"
- **Cursor** = a whole new IDE. You switch away from VS Code (though it feels identical). AI is woven into every keystroke.
- **GitHub Copilot** = a plugin. You stay in VS Code (or JetBrains, or Xcode). Lower disruption, lower cost ($10/month vs. $20/month).
- Both can use the same underlying GPT-5.x or Claude models.

### "LangChain vs. Claude Code"
- **LangChain / LangGraph** = a developer framework (Layer 5) for *building* AI apps. Engineering tool.
- **Claude Code** = an end-user developer tool (Layer 4). A product you use.
- A software team might *use* LangChain to build something *like* Claude Code for their company.

### "IDE vs. IDE Extension vs. CLI"
- **IDE** = the whole editor. Cursor and Zed are IDEs. You open them instead of VS Code.
- **IDE Extension** = a plugin installed *inside* your existing editor. GitHub Copilot is an extension.
- **CLI** = runs in a terminal window. No visual editor at all. Claude Code CLI is a CLI.

### "Gemini vs. Google"
- **Google / Google DeepMind** = the lab (Layer 1).
- **Gemini** = the model family (Layer 2): Gemini 3.1 Pro, Gemini 3 Flash, etc.
- **Gemini** (the app) = the consumer chat product (Layer 3), like ChatGPT but from Google.
- **Gemini Code Assist** = the IDE extension (Layer 4).
- **Google Antigravity** = a new AI-native IDE (also Layer 4).
- Same word, four different layers.

---

## How the Layers Connect

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 6: Inference Providers                                   │
│  (OpenAI API · Anthropic API · Bedrock · Vertex · OpenRouter)  │
└──────────────────────────────┬──────────────────────────────────┘
                               │ serve weights to
┌──────────────────────────────▼──────────────────────────────────┐
│  Layer 2: Foundation Models                                     │
│  (GPT-5.5 · Claude Opus 4.7 · Gemini 3.1 Pro · Kimi K2.5 ...)  │
└────────────┬──────────────────────────────────────┬────────────┘
             │ power                                 │ power
┌────────────▼───────────────┐   ┌──────────────────▼───────────┐
│  Layer 3: Consumer Apps    │   │  Layer 4: Developer Tools    │
│  (ChatGPT · Claude.ai ·    │   │  (Cursor · Copilot ·         │
│   Gemini · Grok ...)       │   │   Claude Code · Codex ...)   │
└────────────────────────────┘   └──────────────────────────────┘
                                                  ▲
                                                  │ built with
                                 ┌────────────────┴─────────────┐
                                 │  Layer 5: Frameworks         │
                                 │  (LangGraph · CrewAI ·       │
                                 │   AutoGen · PydanticAI ...)  │
                                 └──────────────────────────────┘
     ┌─────────────────────────────────────────────────────────┐
     │  Layer 1: AI Labs (train and update the models)         │
     │  (OpenAI · Anthropic · Google · Meta · xAI · Mistral …) │
     └─────────────────────────────────────────────────────────┘
```

---

## Quick Reference: What Am I Looking At?

| You hear... | It lives in... | It is a... |
|-------------|---------------|-----------|
| OpenAI, Anthropic, Google DeepMind | Layer 1 | A company that trains AI models |
| GPT-5.5, Claude Opus 4.7, Gemini 3.1 Pro | Layer 2 | A set of trained model weights |
| ChatGPT, Claude.ai, Gemini app | Layer 3 | A consumer chat application |
| Cursor, Windsurf, Zed | Layer 4a | An AI-native IDE (replaces VS Code) |
| GitHub Copilot, Gemini Code Assist | Layer 4b | An IDE extension (plugin for your existing editor) |
| Claude Code CLI, Codex CLI, Aider | Layer 4c | A terminal agent (no GUI) |
| Claude Code Desktop, chatgpt.com/codex | Layer 4d | A GUI coding agent app |
| LangChain, CrewAI, AutoGen, PydanticAI | Layer 5 | A developer framework for building AI apps |
| Bedrock, Vertex AI, Ollama, OpenRouter | Layer 6 | Inference infrastructure (where the model runs) |

## See Also

- [Model Context Protocol (MCP)](mcp.md) — the standard that connects Layer 4 tools to external tools and data
- [Agent-to-Agent Protocol (A2A)](a2a.md) — how Layer 4/5 agents communicate with each other
- [6 Agent Design Patterns](../patterns/agent-design-patterns.md) — the recurring patterns used in Layer 5 frameworks
- [Managed Agent Platforms — Comparative Overview](agent-platforms.md) — deeper dive into hosted agent runtimes
