---
name: price-hunt
description: Structured research for one-off purchases. Interviews the user briefly, runs a normalized web research pass, then either recommends buying now or saves the item to a file-based watchlist for later re-checking. Use when the user wants to find the best price on a specific item (flight, hotel, tool, electronic, appliance, etc.), or when they ask to list, re-check, or close existing price watches.
---

# price-hunt

A prompt-driven skill for irregular, one-off purchase decisions. Goal: stop the user from over-researching, prevent overpaying, and remember items that should be revisited later — without hardcoding category-specific retailer lists or promising fake precision on "fair price" estimates.

**The skill supports two modes of equal weight:**

- **Immediate purchases** — the user wants to buy soon and is willing to act today if the price is right (typical flight, hotel, tool).
- **Long-horizon price targets** — the user is willing to wait weeks or months for the right price (typical smartphone, laptop, appliance, anything tied to a product cycle or seasonal sale).

Long-horizon watches remain active until they are closed, expired, or manually abandoned. The skill is not a daemon and does not check prices in the background; long-horizon support means durable file-based state that survives across many sessions, not autonomous monitoring.

## When to use this skill

Use when the user can name **the exact product** (or products) to price, OR when handed a shortlist bundle from `product-shortlist`. Operational test: *Claude does not need to make a model-selection judgment.*

Examples:

- "Find the best price on a Galaxy S25 Ultra"
- "Should I wait 2 months on a Pixel 9?"
- "Price these 3 helmets: Giro Register, Smith Signal, Specialized Align II"
- A `product-shortlist` handoff bundle is provided

## When NOT to use this skill (bounce to `product-shortlist`)

If the user names a **category, problem, or buying goal** rather than a specific model — and Claude would have to *pick which product* — do not start pricing. Instead, state once:

> "This sounds like a 'what should I buy' question rather than a 'where's the best price' question. The `product-shortlist` skill is the right entry point — it produces 3-5 candidates, then hands the finalists back to me for pricing. Want to switch over?"

Wait for the user's answer. Do not auto-invoke `product-shortlist`; let the user choose. If they insist on price-hunting a vague request anyway, proceed but state the caveat that the result may not match what they actually want.

Examples of requests to bounce:

- "What's the best phone under $800?" → bounce
- "I need a bike helmet" → bounce
- "Recommend a laptop for travel" → bounce

## Invocation contract

The skill activates on user intents like:

- "Find me the best price on a DeWalt 20V circular saw"
- "Help me buy a flight to Lisbon in July"
- "Is $850 a good price for [model]?"
- "Show my price watches" / "list watches"
- "Re-check my circular saw watch" / "re-check <slug>"
- "Close the laptop watch"

The skill is **prompt-driven**. There are no CLI flags. Watch operations are triggered by natural language, and the skill maps them to file operations in `~/.claude/price-watches/`.

## Phase 1 — Intake (ask only what's missing)

### Input modes

The skill accepts two input shapes:

**Mode 1 — single concrete target (default).** The user names one product. Run the three-question intake below.

**Mode 2 — shortlist bundle (from `product-shortlist`).** The user pastes (or this session contains) a YAML block whose first line is `handoff_to: price-hunt`. When present:

- **Skip the intake questions.** All required fields (`user_goal`, `budget`, `currency`, `time_horizon`, `patience_window`, `constraints`, `candidates`) come from the bundle.
- **Honor `recommended_next_step`:** if `compare_all`, run the multi-candidate research pass (see Phase 2). If `one_target`, ask the user to pick which `preferred_finalist` to price; then run the standard single-target pass.
- **Treat each candidate's `target_price_band` as a soft anchor.** Confidence labels carry over to fair-price-band labels in the output. `confidence: unknown` means no anchor — fall back to current normalized totals only.
- **Bundle `constraints:` flow directly into watch `constraints:`** if a watch is created. No translation.

If a bundle is malformed (missing required fields, wrong shape), state what's missing, ask the user to re-supply or fall back to single-target intake. Do not silently fill in defaults.

### Single-target intake

Ask these three questions **only if the user hasn't already supplied the answer**. Do not ask all three at once — ask one at a time, and skip any already answered.

1. **What are you buying?** Specific model/spec if known. For travel: route, dates (or date range), pax.
2. **Budget ceiling or target price?** The price at or below which the user will buy without further hunting.
3. **Time horizon?** `today` / `this month` / `flexible` / `long_horizon`. This drives the buy-now-vs-watch decision.

If the user picks `long_horizon`, or the item is one where long waits are common (smartphone, laptop, GPU, console, appliance, anything with a known product cycle or seasonal sale pattern), ask one optional follow-up:

> **Patience window?** `~1 month` / `~3 months` / `until next product cycle` / `open-ended`

This is recorded on the watch and used to compute `next_check_after` and `expires_at`. If the user picks `open-ended`, no expiry is set — the watch persists until manually closed.

Do not ask about condition (new/used/refurb), brand preferences, or deal-breakers unless they become relevant during the research pass. Volunteered constraints are honored; unprompted interrogation is not.

## Phase 2 — Research pass (single, normalized)

Run **one** web research pass using WebSearch. Claude picks sources appropriate to the item using general knowledge. **No category-to-retailer mapping is baked into the skill.** See the non-normative source hints in the appendix at the bottom of this file for examples Claude may draw on, but those are illustrative only.

### Market defaulting (mandatory — do not skip)

The user's market drives which retailers, which currency, and which availability/warranty/returns realities apply. Get this right **before** running any search.

Determine the user's market in this order:

1. **Explicit constraint in this conversation** — if the user said "in Canada", "shipping to Germany", "EU pricing", etc., use that.
2. **Handoff bundle `constraints.region`** — if invoked from a `product-shortlist` bundle that set `region`, use that.
3. **Environment context** — if the conversation's system context, the user's profile, or other clearly available signal indicates a country (e.g. CLAUDE.md, prior turns in the session, an obvious locale hint), use that.
4. **Ask once** — if none of the above gives a clear answer, ask: *"What country/market are you buying in? This affects retailers, currency, and warranty."* Do not guess.

**Never default silently to the United States.** US sources are easier to find on the open web, but defaulting to them when the user is elsewhere is a real failure mode. If market is unknown after step 3, stop and ask; do not proceed with a US-shaped search.

Once market is set:

- **Retailers**: search the user's domestic retailers first. For Canada: Amazon.ca, Best Buy Canada, Canadian Tire, Home Depot Canada, Walmart Canada, Newegg.ca, manufacturer Canadian storefronts, Canada Computers, Memory Express, MEC for outdoor, etc. For other markets: pick analogous domestic retailers using general knowledge. **Do not substitute the US version of a retailer for the local one** (Amazon.com is not a substitute for Amazon.ca).
- **Currency**: price everything in the user's local currency. Set `currency:` accordingly in any watch file. Do not mix currencies in the ranked table.
- **Availability / warranty / returns**: when normalizing offers, use the realities of the user's market (e.g. Canadian warranty terms, Canadian return windows, GST/PST/HST implications when known).

**Cross-border (foreign) offers** may only be surfaced when:

- The user explicitly asks for US/foreign sources, OR
- Domestic availability is genuinely weak (item not sold domestically, all domestic sellers out of stock, or domestic price is dramatically out of line with the global market).

When a cross-border offer is included, it MUST be **clearly labeled as cross-border** in the ranked table's `notes` column, and the label must call out the relevant friction: **FX conversion**, **import duties/brokerage**, **shipping cost across borders**, **warranty void or non-honored locally**, and **return-shipping cost on a return**. Do not present a cross-border offer alongside domestic offers as if they were equivalent.

Record the resolved market in any watch file's `constraints.region` (use the ISO country code, e.g. `CA`, `US`, `GB`, `DE`).

### Multi-candidate variant (shortlist bundle, `compare_all`)

When invoked from a shortlist bundle with `recommended_next_step: compare_all`, the research pass runs once **per candidate** (in parallel where possible) and produces a **comparison table across candidates**, not across offers for one candidate. Columns: candidate name, best current normalized price, source, condition, vs. `target_price_band` (under / within / above), notes.

The comparison output identifies one **"best current buy"** — the candidate where the gap between current price and `target_price_band` is most favorable, weighted by confidence. State the reasoning in one sentence.

From there, Phase 4 exits apply **per candidate**: the user can `buy_now` one, `create_watch` another, and `no_action` the third in a single session. The skill names each exit explicitly. Do not drift back into broad product research — if the user starts asking "what about X that wasn't in the shortlist?", state once: *"That's a `product-shortlist` question. Want to step back?"*

### Normalization rules

For each offer, attempt to capture:

- Base price
- Shipping cost (or "free" / "missing")
- Tax (or "missing" — most US sites don't show pre-checkout)
- Condition — stored value (one of: `new`, `refurb`, `used`, `open_box`, `unknown`). User-facing prose may say "open-box" or "open box" but the **stored** value in any YAML, watch file, or `constraints:` block MUST be the canonical snake_case form: `open_box`. Same rule for any other multi-word condition that arises.
- Warranty (manufacturer / seller / none / unknown)
- Seller / source (Amazon 1P, third-party, manufacturer direct, marketplace, etc.)
- Currency (flag if non-USD)

### Missing-information policy (do not estimate)

- **Never estimate missing shipping or tax.** Show as "missing" in the row.
- **Rank complete offers above incomplete offers when normalized totals are close** (within ~5%).
- **If an incomplete offer is currently cheapest, mark it as "provisionally cheapest — shipping/tax missing"** rather than asserting it wins.
- **If a majority of offers are incomplete, downgrade the overall recommendation confidence** explicitly.

### Output: ranked table

**Default to a markdown table whenever there are 2 or more comparable offers.** A repeated numbered list with per-offer blocks is harder to scan and is the wrong default. Columns: rank, price (normalized total or `partial`), source, condition, warranty, link, and a `notes` column for caveats (missing data, restocking fees, return policy red flags, etc.).

Use a list format **only** when:

- There is exactly one offer worth showing, or
- Offers are too sparse or too heterogeneous to align as rows (e.g. one is an annual subscription, one is a one-time hardware buy, one is a multi-line travel itinerary), or
- The user has explicitly asked for a list.

**Conditional offers (trade-in required, coupon stack required, loyalty/membership price, carrier lock, financing-only price, etc.) must never be flattened into the same simple ranking as unconditional offers without labeling.** Pick one of these two presentations:

- **Two-table form**: a main table of unconditional offers, then a smaller secondary table labeled "Conditional offers" with the same columns plus a `requires` column.
- **Single-table form**: one table that adds an explicit `pricing_basis` (or `requires`) column. Every row fills that column — `unconditional` for plain prices, or a short phrase like `trade-in S22+`, `requires Costco membership`, `with 24-mo carrier plan`, `coupon SAVE10`, etc.

Pick whichever form keeps the ranking honest. A trade-in price of $400 is not directly comparable to a plain $700 price; the column or split table makes that obvious.

### Fair-price estimate (optional, confidence-labeled)

Only include a fair-price band if it can be supported. Label confidence explicitly:

- **high** — price-history data found (Keepa, CamelCamel, historical fare data) or MSRP + consistent street price
- **medium** — three or more independent current offers cluster around a price
- **low** — single anchor or thin sourcing
- **unknown** — do not invent a band; say "no reliable fair-price reference found"

## Phase 3 — Iterate on demand

After the first pass, **default to offering one refinement round** ("want me to narrow to refurb only? exclude Amazon? widen dates?"). The user drives this. Re-run Phase 2 with the new constraint.

**After round 2**, if the user asks for more, comply, but state once:

> "Additional searching is unlikely to materially improve the result unless constraints change. Want to change a constraint, or should we decide?"

Do not enforce a hard cap. The user controls iteration depth.

## Phase 4 — Decision and exit

Three exits — `buy_now`, `create_watch`, or `no_action`. The skill must name the exit explicitly in its final message so the user knows what state they're leaving in.

### Exit A — `buy_now`

Conditions: lowest normalized offer ≤ target price, OR user explicitly says "I'll take it." Output:

- Final recommended offer (source + link + total)
- 30-second pre-purchase checklist:
  - Return policy / restocking fee
  - Warranty terms
  - Coupon / cashback stack check (Honey, Rakuten, manufacturer codes)
  - Payment method protection (card chargeback, PayPal, etc.) — flag only for higher-risk sellers
- Do not write a watch file.

### Exit B — `create_watch`

Conditions: lowest offer > target AND user not willing to pay current price, OR user says "wait." Action:

1. Generate a slug (kebab-case, derived from item description, e.g. `dewalt-20v-circular-saw`).
2. Check `~/.claude/price-watches/` for an existing watch with the same slug.
   - If exists and `status: active`: ask the user whether to **update** (overwrite constraints) or **create a separate variant** (append `-v2`, `-refurb`, etc.).
   - If exists and `status: closed` or `expired`: create new, do not reuse the closed file.
3. **Record why waiting makes sense.** Before writing the file, state and store a `wait_rationale` — a short reason such as: *"new model expected in September"*, *"current price ~15% above 6-month median"*, *"Black Friday is 4 weeks away"*, *"target price requires a sale event"*, *"user simply wants to wait"*. If no real reason exists, say so plainly (`"no strong signal — user-driven wait"`) rather than inventing one.
4. Write the watch file (schema below). The watch's `constraints:` block MUST capture every search parameter needed to faithfully reproduce the research pass on re-check (see schema).
5. State the `next_check_after` date (and `expires_at` if set) and remind the user that re-checks are manual ("ask me to re-check it anytime").

### Exit C — `no_action`

Conditions: the user decides not to buy and does not want a watch — typical when the horizon was `today` and the price isn't right, or when the user simply walked away mid-conversation. Action:

- Do not write a watch file.
- State explicitly: *"Exiting with no action. No watch saved. Ask again anytime."*
- This exit exists so the skill never silently terminates and never quietly creates a watch the user didn't ask for.

## Watch file schema

Location: `~/.claude/price-watches/<slug>.md`. Create the directory if missing.

### Output hygiene for persisted watch files (mandatory)

Watch files are written to disk and re-read later by Claude. They MUST use **plain ASCII punctuation only**. Do not use smart/typographic characters in any field, comment, note, rationale, or check-history entry. Specifically:

- Use ASCII hyphen `-` only. **Never** en dash (U+2013) or em dash (U+2014).
- Use straight quotes `'` and `"` only. **Never** curly/smart quotes (U+2018, U+2019, U+201C, U+201D).
- Use ASCII `...` for ellipsis, not U+2026.
- Use ASCII `~` for approximate, not U+2248.
- Avoid arrows (`->`, not `→`), comparison glyphs (`<=`, `>=`, not `≤`/`≥`), and other Unicode symbols in stored content.

Non-ASCII characters are only acceptable in a watch file when they are part of source content the user supplied verbatim (e.g. a non-English product name) or part of a URL. Everything Claude writes — rationales, notes, history entries, schema values — must be plain ASCII.

User-facing chat messages may continue to use typographic punctuation freely; this rule applies only to text that is **persisted** to a watch file.

```markdown
---
slug: dewalt-20v-circular-saw
status: active            # active | closed | expired
item: DeWalt 20V Max circular saw (DCS391B)
target_price: 120
currency: USD
time_horizon: flexible    # today | this_month | flexible | long_horizon
patience_window: null     # ~1mo | ~3mo | next_product_cycle | open_ended | null
wait_rationale: "current price ~12% above 6-month median; spring sales likely"   # ASCII only; no smart punctuation
constraints:              # everything needed to faithfully reproduce the search
  condition_ok: [new, refurb]
  exclude_sellers: []
  region: US
  # travel example fields, used when relevant:
  # route: "BUD-LIS"
  # date_range: "2026-07-01..2026-07-15"
  # pax: 2
  # nights: 5
  # cabin: economy
  # free-form extras allowed:
  # min_warranty_months: 12
created: 2026-05-17
last_checked: 2026-05-17
last_result:
  price: 135
  source: Lowes
  condition: new
  url: https://...
next_check_after: 2026-06-01
expires_at: null          # date; null means open-ended, never auto-expire
closed_at: null
close_reason: null        # bought | no_longer_needed | expired | superseded | abandoned
sources_tried: [amazon, homedepot, lowes]
---

## Notes

User flexible on timing. Fair-price band: $130-150 (confidence: medium,
based on 3 current offers + 1 historical reference).

## Check history

- 2026-05-17: lowest $135 @ Lowes (new), watch continues. Target $120.
```

### Constraints block

`constraints:` is the **single source of truth** for everything needed to re-run the search faithfully. Well-known keys (use when applicable):

- `condition_ok` — list from the canonical condition enum: `new`, `refurb`, `used`, `open_box`, `unknown`. Example: `[new, refurb, open_box]`. Never use hyphenated forms like `open-box` in stored YAML.
- `exclude_sellers` — list of source names the user ruled out
- `region` — country/locale, when it materially affects pricing or availability
- **Travel-specific**: `route`, `date_range`, `pax`, `nights`, `cabin`, `flexible_dates`, `nearby_airports`
- **Hardware-specific**: `min_warranty_months`, `min_spec` (free-form string)

Additional free-form keys are allowed. The contract: **a re-check must read `constraints:` and reproduce the same search** (with refreshed prices). If the user adds a new constraint during a re-check, persist it back to `constraints:`.

### Lifecycle rules

- **`next_check_after`** is set by the skill based on time horizon:
  - `today` → no watch (force decision in this session)
  - `this_month` → 5–7 days out
  - `flexible` → 2–4 weeks out
  - `long_horizon` → 4–8 weeks out (or aligned with `wait_rationale`, e.g. "1 week before expected product launch")

  The skill states the chosen date; the user can override.
- **`expires_at`** is set from the patience window:
  - `~1 month` → ~30 days from `created`
  - `~3 months` → ~90 days from `created`
  - `next_product_cycle` → best-guess date based on item (state the assumption, let user override); leave null if no defensible date
  - `open_ended` or null → `expires_at: null`, watch never auto-expires
- **On re-check**: update `last_checked` and `last_result`, append to `## Check history`. If target met, propose closing with `close_reason: bought` (only after user confirms purchase). Otherwise leave active and recompute `next_check_after`. Long-horizon watches stay active across many re-checks — that is the point.
- **Expiry**: only triggered by `expires_at` being in the past, never by inactivity alone. On the next "list watches" call, flag any expired watches and offer to close (`close_reason: expired`) or extend.
- **Open-ended watches never auto-expire.** They are flagged on `list` if `last_checked` is older than 6 months, with a gentle "still interested?" prompt — but the watch is not closed without explicit user action. `close_reason: abandoned` is the right label if the user no longer cares.
- **Closing**: never silently delete a watch file. Set `status: closed`, fill `closed_at` and `close_reason`. Files are kept for history.
- **Dedup**: same slug + `status: active` → ask the user (see Phase 4 Exit B step 2). Never auto-merge.

## Watch operations (prompt-driven)

| User intent | Action |
|-------------|--------|
| "show my price watches" / "list watches" | Read `~/.claude/price-watches/*.md`, show active watches as a table (slug, item, target, last_result.price, last_checked, next_check_after). Flag any **expired** watches (`expires_at` in the past), and flag any **open-ended** watches whose `last_checked` is older than 6 months. Do not use a single global staleness threshold — see lifecycle rules. |
| "re-check <slug>" or "re-check my <item> watch" | Find the file, run Phase 2 with the watch's stored constraints, update fields, report result. |
| "close <slug>" | Set `status: closed`, prompt for `close_reason`, fill `closed_at`. |
| "show closed watches" | List files where `status != active`. |

If the user refers to a watch ambiguously ("my saw watch") and multiple match, list candidates and ask which.

## Stopping rule (evidence-based, not iteration-count)

The skill nudges toward a decision when **any** of these hold:

- Four or more unique sources checked
- Spread between best and second-best normalized offer is less than ~5%
- The last refinement round did not produce a materially better result (no new sources, no price improvement >5%)
- No new constraint was introduced in the last round

When two or more of these hold, the skill explicitly states the situation and asks for a buy/wait decision rather than offering another round.

## What this skill does not do (v1 scope)

- **No scheduled background monitoring.** Re-checks are user-triggered. Scheduling via `/schedule` is a future integration.
- **No multi-currency conversion.** Flag non-USD offers; do not convert.
- **No automated checkout.** The skill recommends; the user buys.
- **No category-specific retailer lists baked into the skill.** Claude picks sources per item using general knowledge.
- **No fair-price estimation without supporting data.** "Unknown" is a valid answer.

## Storage and deployment

- **Skill file**: `~/.claude/skills/price-hunt/SKILL.md`, deployed from the dotfiles repo via `bash install.sh`.
- **Watch data**: `~/.claude/price-watches/` — personal, not in the dotfiles repo, never committed.
- **Backups**: the standard `install.sh` `.backup-*` mechanism covers the skill file; watch data is the user's responsibility (it is plain markdown; back up if it matters).

## Appendix: source hints (non-normative)

These are illustrative starting points Claude may use when picking sources. They are **not part of the contract** — Claude is free to choose differently based on the specific item, region, or user constraints.

- **Flights** — Google Flights, Skyscanner, Kayak, airline direct
- **Hotels** — Booking, Hotels.com, hotel direct, occasionally Airbnb for longer stays
- **Amazon-likely consumer goods** — Amazon (+ Keepa or CamelCamel for price history if findable), Best Buy, B&H, manufacturer direct/refurb store
- **Tools and home equipment** — Home Depot, Lowe's, Amazon; Facebook Marketplace or Craigslist if used is acceptable
- **Software/SaaS** — vendor pricing page, annual-vs-monthly comparison, AppSumo or similar deal sites for indie tools

Region and currency override these defaults. For non-US users, regional retailers should take precedence.
