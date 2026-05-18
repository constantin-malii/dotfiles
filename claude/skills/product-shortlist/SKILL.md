---
name: product-shortlist
description: Turns a vague product or category need ("I need a bike helmet", "best laptop under $1500 for travel") into 3-5 concrete candidates worth pricing. Asks a short intake, surfaces options with tradeoffs and rough price bands, and hands off the chosen 1-2 finalists to the price-hunt skill. Use when the user names a category, problem, or use case rather than a specific model. Do not use when the user already knows the exact product — route directly to price-hunt instead.
---

# product-shortlist

A prompt-driven skill for the **upstream** half of a purchase decision: "What should I buy?" — not "where's the best price?". It exists so the user does not have to do hours of category research before reaching the pricing/timing/watch logic in `price-hunt`.

The skill ends with one of:

- A handoff bundle (YAML) recommending 1-2 candidates to take into `price-hunt`, or
- The user deciding the category isn't worth pursuing right now (`no_action`).

It does **not** create watches, does **not** track prices over time, and does **not** drift into endless review aggregation. Watches are `price-hunt`'s job.

## When to use this skill

Use when the user names a **category, problem, or buying goal** rather than a specific model:

- "I need a bike helmet"
- "Best phone under $800"
- "What laptop should I buy for travel and battery life?"
- "Looking for a good chef's knife"
- "Need a router for a 3-bedroom apartment"

## When NOT to use this skill

Route directly to `price-hunt` instead when the user can name the exact product:

- "Find the best price on a Galaxy S25 Ultra" → `price-hunt`
- "Should I wait 2 months on a Pixel 9?" → `price-hunt`
- "Price these 3 helmets I already picked" → `price-hunt` (shortlist-bundle mode)

**Operational test:** if Claude can name the exact product to price without making a model-selection judgment, this is a `price-hunt` job. If Claude would have to *pick which model*, this skill is correct.

## Invocation contract

Prompt-driven. The skill activates on user intents like:

- "Help me pick a bike helmet"
- "What's the best laptop for travel under $1500?"
- "I need to buy a chef's knife, what should I get?"
- "What router should I get for my apartment?"

There are no CLI flags. The skill terminates with a final message that is either a YAML handoff bundle or a `no_action` exit statement.

## Phase 1 — Intake (minimum viable)

Ask only what's missing. One question at a time. Stop asking the moment Claude has enough to produce a defensible shortlist.

Required:

1. **Product type / category.** What are you trying to solve or buy? Get the use case, not just the noun. ("Bike helmet for commuting in rain" is different from "bike helmet for downhill MTB.")
2. **Budget.** Approximate ceiling — a number or a range. Open-ended ("doesn't matter") is allowed but rare.
3. **Use case.** How will you use it? Frequency, environment, key activities. This is the most important question — most "what should I buy" mistakes come from skipping this.
4. **Must-haves / deal-breakers.** Specific features the user requires or refuses. Wait for these to be volunteered or surface naturally; do not interrogate.

Optional (ask only if signal is weak after the four above):

5. **Urgency.** Affects whether to favor in-stock-now candidates vs. ideal picks.
6. **Brand preferences or exclusions.** Volunteered loyalties or aversions.

Skip any question the user has already answered. Skip optional questions unless the shortlist would meaningfully change without them.

**Region is not optional.** It is resolved separately, before the research pass — see "Market defaulting" in Phase 2 below. Do not ask it as part of the intake if it can be determined from context.

## Phase 2 — Research and shortlist

### Market defaulting (mandatory — do not skip)

The user's market drives which products are actually available, which currency the price band should be in, and which retailers the downstream `price-hunt` will query. Resolve this **before** running the research pass.

Determine the user's market in this order:

1. **Explicit constraint in this conversation** — "in Canada", "available in the UK", "EU market", etc.
2. **Environment context** — system context, CLAUDE.md, conversation history, or other clearly available locale signal.
3. **Ask once** — if neither of the above gives a clear answer, ask: *"What country/market are you buying in? This affects which models are available and which retailers I'll point to."* Do not guess.

**Never default silently to the United States.** US-market candidates are easier to find on the open web, but defaulting to them when the user is elsewhere produces shortlists with unavailable products, wrong currency price bands, and irrelevant retailer suggestions for the downstream `price-hunt` handoff.

Once market is set, the shortlist MUST reflect it:

- **Availability** — every candidate must be actually buyable in the user's market. Exclude products that are not sold there, region-locked, or only available via grey-market import (unless surfaced explicitly as cross-border, see below).
- **Price bands** — `target_price_band` values are in the user's local currency. Set `currency:` in the handoff bundle accordingly (e.g. `CAD` for Canada, `GBP` for UK, `EUR` for eurozone).
- **Source examples used during research** — prefer domestic review sites and domestic retailer pricing when forming the band. For Canadian users: Canadian retailers (Amazon.ca, Best Buy Canada, Canadian Tire, MEC, Memory Express, Canada Computers, etc.), Canadian review coverage where available. Do not substitute the US version of a retailer for the local one when assessing availability or price.

**Cross-border candidates** may only appear in the shortlist when:

- The user explicitly asks for foreign-market options, OR
- Domestic availability is genuinely weak (item category not sold locally; all credible candidates are import-only).

When a cross-border candidate is included, it MUST be **labeled as cross-border** in the rationale, with a one-line note that the downstream `price-hunt` will need to treat FX conversion, import duties / brokerage, cross-border shipping, and warranty-not-honored-locally as explicit friction. Carry this signal forward in the handoff bundle by setting `constraints.region` to the user's market and including a free-form `constraints.cross_border_ok: true` flag.

Record the resolved market in the handoff bundle as `constraints.region` using the ISO country code (e.g. `CA`, `US`, `GB`, `DE`).

### Research pass

Run **one** research pass (WebSearch + general knowledge) to produce **3-5 candidates**. Fewer than 3 is acceptable only if the category genuinely has few credible options. More than 5 is forbidden — the point of this skill is to narrow, not enumerate.

For each candidate, capture:

- **Name** (specific enough that `price-hunt` can find it: brand + model)
- **Why it's good** — one sentence; what role this candidate plays in the shortlist (value pick, premium pick, niche feature, etc.)
- **Key tradeoffs** — what's worse about it relative to the others
- **Rough street-price band** — two numbers (low, high) in the user's currency, or `unknown` if no defensible band exists
- **Confidence** — `high` / `medium` / `low` / `unknown` on the price band specifically (not on the recommendation)

**Tradeoff honesty rule:** Do not pretend there is one objectively "best" choice when tradeoffs dominate. The shortlist's job is to map the tradeoff space, not collapse it. If three candidates each win on different axes, say so.

**Price band confidence labels:**

- `high` — strong street-price signal across multiple current sources or recent historical data
- `medium` — a couple of current sources agree
- `low` — single source or noisy data
- `unknown` — no defensible band; let `price-hunt` discover the price

## Phase 3 — Narrow to finalists

Present the shortlist as a table or labeled list. Then explicitly recommend **1-2 candidates** worth taking into `price-hunt`, with a one-sentence justification per recommendation.

The user can:

- **Accept** the recommendation and continue to handoff
- **Pick different finalists** from the shortlist
- **Request one round of refinement** — narrow the criteria, swap a candidate, or ask "what else exists in X niche?" This is allowed exactly once by default. Further rounds require the user to introduce a new constraint; otherwise the skill states "additional candidates are unlikely to materially change the tradeoff map" and pushes for a decision.
- **Walk away** (`no_action`)

## Phase 4 — Exit

Three exits, all named explicitly in the final message.

### Exit A — `handoff_to_price_hunt` (the primary success path)

Output the handoff bundle as a YAML code block. Schema:

```yaml
handoff_to: price-hunt
source_skill: product-shortlist
user_goal: <one-line restatement of what the user is trying to accomplish>
budget: <number>
currency: <ISO code, e.g. USD>
time_horizon: <today | this_month | flexible | long_horizon>
patience_window: <~1mo | ~3mo | next_product_cycle | open_ended | null>
constraints:
  region: <country/locale or null>
  must_have: [<list of required features or specs>]
  exclude: [<list of explicit exclusions>]
  # plus any free-form keys volunteered by the user
candidates:
  - name: <brand + model>
    rationale: <one sentence on why this is in the shortlist>
    target_price_band: [<low>, <high>]   # or "unknown"
    confidence: <high | medium | low | unknown>
  # 3 to 5 entries total
recommended_next_step: <one_target | compare_all>
preferred_finalists: [<1 or 2 candidate names>]
```

The final user-facing message should:

1. State explicitly: *"Exit: handoff_to_price_hunt. Bundle below — paste into a new price-hunt session or continue here."*
2. Show the YAML block.
3. Stop. Do not start pricing. Pricing is `price-hunt`'s job.

### Exit B — `delivered_shortlist_no_handoff`

Conditions: user wants the shortlist but isn't ready to price yet (still deciding, planning to think about it, comparing notes elsewhere). Action: present the shortlist with rationale/tradeoffs/price bands, but do not produce a handoff bundle. State explicitly: *"Exit: delivered_shortlist_no_handoff. No handoff to price-hunt. Run price-hunt later when you're ready."*

### Exit C — `no_action`

Conditions: user decides the category isn't worth pursuing right now, or walks away mid-conversation. State explicitly: *"Exit: no_action. No shortlist saved. Ask again anytime."*

## Stopping rules

Stop researching and push for a decision when any **two** of the following hold:

- The shortlist already contains a clear value pick, a premium pick, and a niche pick (canonical tradeoff coverage)
- The last refinement round did not change the tradeoff map
- The user has not introduced any new constraint in the last round
- Five candidates have been considered (even if some were rejected) — there is no need to enumerate a sixth

## What this skill does not do

- **No watches, no file persistence.** Shortlists are ephemeral. The output is the handoff bundle in chat; if the user wants durable state, that's `price-hunt`'s watch mechanism.
- **No deep current-price normalization.** Price bands here are rough anchors; `price-hunt` does the normalized comparison with shipping/tax/condition.
- **No buy-now-vs-wait recommendation.** That is `price-hunt`'s job (it has the wait_rationale, watch logic, and the current normalized totals to support such a call).
- **No review-site aggregation past what's needed for the shortlist.** If the user wants a deep review, point them to Rtings, Wirecutter, etc.; do not become a review aggregator.
- **No category-specific scoring rubrics baked in.** Use general knowledge and web search; do not hardcode "for helmets, weight matters more than vents."

## Storage and deployment

- **Skill file**: `~/.claude/skills/product-shortlist/SKILL.md`, deployed from the dotfiles repo via `bash install.sh`.
- **No persistent data.** The skill writes nothing to disk. Any durable state belongs to `price-hunt`.

## Appendix: example sources (non-normative)

These are illustrative starting points for the research pass. Claude is free to choose differently based on the category and region.

- **General consumer goods**: Wirecutter, Rtings, manufacturer comparison pages, top-3 retailer search hits
- **Tech**: GSMArena, Notebookcheck, Tom's Hardware, AnandTech (where still relevant)
- **Outdoor / sports**: REI guides, Outdoor Gear Lab, BikeRadar (cycling), evo (snow)
- **Kitchen**: Serious Eats, America's Test Kitchen, Cook's Illustrated
- **Audio**: Rtings, What Hi-Fi, head-fi (headphones)

Use one or two appropriate to the category. Do not aggregate every site that exists.
