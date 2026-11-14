"""
The writing guide of a single post's sketch, merge and revise calls, ported from
pumpkit-new-architecture-v5, and the sections it shares with a Thread's guide (`thread_guide.py`).

`writing_guide(plan, char_limit)` assembles it from fixed sections (content rules, hook craft,
closer and CTA rules, rhythm) and one tailored section for each of the Plan's choices: funnel,
desired action, length and structure. Only the section for the chosen value goes into the prompt.
"""

from dataclasses import asdict, dataclass
from typing import Literal, Optional

from pumpkit.posts.formats import FORMAT_THREAD
from pumpkit.posts.plans import (
    FUNNEL_ACTIONS,
    LENGTH_SHORT,
    THREAD_STRUCTURES,
    DesiredAction,
    Funnel,
    Length,
    Plan,
    Structure,
)

# v5's limits. Each prompt states the lower of one of these and the account's own limit.
SHORT_LIMIT = 280
MEDIUM_LIMIT = 700
LONG_LIMIT = 25_000
# What shows in the feed before "Show more" on a long post.
PREVIEW_CHARS = 280

PromptFunnel = Literal["TOF", "MOF", "BOF"]
# The funnel stages as the prompts name them.
PROMPT_FUNNELS: dict[Funnel, PromptFunnel] = {"top": "TOF", "middle": "MOF", "bottom": "BOF"}

CONTENT_RULES = """\
# The raw input is the content

- Say what the raw input says. If it states a position, the post states that position.
- Do not add an opinion the raw input does not hold. Do not invent a conclusion I did not reach.
- Do not invent facts. No numbers, no names, no results, no anecdotes, no links, no specifics that are not in the raw input or the positioning.
- Keep the raw input's concrete details, numbers and turns of phrase. They are what makes the post feel real. Don't sand them into generic statements.
- A rambling raw input is normal: it is spoken, not written. The core idea tells you what is worth posting. Leave out what doesn't serve it.
- Do not describe the raw input back to me. Write the post."""

GOOD_POST = """\
# What a good post does

- It speaks to one specific reader: the audience in my positioning. They are always asking "what's in it for me?"
- It covers one idea: the core idea. Nothing else gets in.
- It gives value: it saves the reader time or earns them money, directly or indirectly.
- It leaves the reader with the takeaway, stated concretely.
- It has no reading friction. A 12-year-old can follow it.
- It is a post I would enjoy reading myself.

The bare minimum, or readers hate it:

- No clickbait. The post delivers what the hook promises.
- No pushy self-promotion. No spam.
- It doesn't sound AI-generated."""

HOOK = """\
# The hook

The hook is the opening of the post: the first one or two sentences. It decides whether the reader stops scrolling. A good hook raises a question in the reader's mind, and they keep reading to answer it.

Work in this order: choose the levers, then choose the hook types, then write the hook.

## Psychological levers

Every strong hook pulls at least one of these, ideally two or three:

- payoff: gets them something concrete (time saved, money, a skill, a shortcut). Tells them the post is worth saving.
- curiosity_gap: opens a loop the brain wants closed.
- surprise: breaks what they expect, or says something they haven't heard before. Includes contrarian takes.
- identity: makes the right person feel seen ("this is about people like me") and part of a group that knows something others don't.
- proof: numbers, names and timeframes make the claim believable.
- exclusivity: makes it feel like insider access.
- loss_aversion: shows what not knowing or not acting costs them (the mistake they're making right now).
- vulnerability: admits a failure, a doubt or a dumb mistake. Builds trust faster than anything else.

## Hook types

Combine two or three of these into one or two sentences. The examples show the shape only: never take their numbers, topics or wording.

- bold_claim: "Copywriting is the most underrated skill on X."
- callout: "If you're a founder with under 1K followers, read this."
- curiosity_gap: "I just realized something 99% of founders miss."
- clear_outcome: "How to write posts like the top 1%."
- contrarian: "F*ck posting volume. You NEED to post less."
- story: "It took me 8 years to realize this..."
- number_list: "7 copywriting rules I wish I knew 6 years ago."
- proof: "This post got 2M views. I analyzed why (takeaways)."

## How to craft it

- Lead with the most interesting thing. Cut the warm-up ("So", "Let me tell you", "In today's world").
- Be specific. "I grew fast" is weak. "I hit 5.8M impressions in my first month" is strong. Numbers, names and timeframes beat vague promises. Use only the ones the raw input gives.
- Make it about the reader.
- Keep it short. Cut every word that isn't doing work.
- Create tension: a question, a surprise, a contradiction, a need for the value. Open a loop the reader needs closed.
- If the best line of the post is at the bottom, move it to the top.
- Be creative. A reader skips a hook they've seen countless times. Stock openers ("Unpopular opinion:", "Hot take:", "Most people don't realize this:", "Here's the thing:") read as boring and as AI.

## The hook must be honest

- It names the topic, so a reader who sees only the hook knows what the post is about.
- It states only numbers, results and claims the raw input gives. "7 lessons" works only if there are seven lessons.
- The rest of the post pays it off. Promise only what the post delivers.
- It leaves the explanation and the details to the lines after it."""

OPENING = """\
# The lines right after the hook

- Cut the fluff and get to the point.
- Show proof and establish credibility as early as you can, with what the raw input and my positioning give you.
- The line after the hook moves forward. It never repeats the hook in other words."""

CLOSER_RULES = """\
- Never trail off. The last line is the second most important line of the post: it tells the reader what to think or do next.
- Ways to close: the takeaway in one or two lines, a specific question, or a tease of what's next.
- The closer is plain and specific to this post. No tweetable pseudo-profound line, no recap of what was just said."""

CTA_RULES = """\
## CTA rules at every stage

- One CTA per post at most. Two CTAs means they do neither.
{external_link}
- The post must be complete without the CTA. Don't withhold the value behind "DM me": it reads as bait.
- Give a reason, don't give an order. "Follow me" is weak. "I'm posting the full build daily" is a reason to follow.
- When an ask fits, prefer one that makes people reply. A good question beats "like and repost".
- No generic engagement bait: no "thoughts?", no "who else?", no "agree?", no "let me know", no "like and repost".
- Never invent an offer, a link, a product, a series or a lead magnet. If the raw input and positioning give nothing to point to, there is nothing to ask for: close on the takeaway.

Weak CTA -> strong CTA (shape only, never copy the wording):

- "Follow for more" -> "I'm documenting the whole build. Follow if you want day 2."
- "Thoughts?" -> "What's the one tool you'd never drop from your stack?"
- "Bookmark this" -> "Save this for the next time your RAG eval looks too good to be true."
- "Link below" -> "{link_example}\""""

RHYTHM = """\
# How the lines read

- One thought per line. A line can hold two short sentences when they form one thought.
- Paragraphs of 1 to 3 lines, separated by a blank line. Group the lines that belong together. A post where every sentence sits alone between blank lines reads as AI "broetry".
- Mix sentence lengths: some short, some longer.
- Talk to the reader: "you" when giving advice. When the raw input is my own experience or result, tell it in first person: that's what makes it credible.
- Simple words. Strong, specific verbs. Active voice.
- Before a list or a sequence of steps, put a short line that tells the reader what is coming.
- Unpolished and sincere. It reads like a person typing on their phone, not like a copywriter. Contractions are fine. Never corporate.
- Don't end a paragraph with a period."""

NEVER_ADD = """\
# Never add

- No hashtags and no emoji, unless the raw input asks for it.
- No headings or titles. No bold, italic or markdown.
- No bullet characters, unless the raw input asks for it. Otherwise list items are plain lines, numbered "1." only when the order or the count matters.
- No em dashes. No "it's not X, it's Y". No "No X. No Y. Just Z."
- Plain text only: it goes straight into the X composer."""

FUNNEL: dict[PromptFunnel, str] = {
    "TOF": """\
# Funnel stage: top of funnel (TOF)

The goal is reach: new people who don't know me yet.

- Short and punchy. Quick value for a broad slice of my audience.
- Assume the reader has never heard of me or my product. No insider context, no jargon they'd need to look up.
- One sharp idea, delivered fast. Don't go deep: depth is for middle of funnel.
- Don't sell anything.""",
    "MOF": """\
# Funnel stage: middle of funnel (MOF)

The goal is trust: the reader has seen me before and is deciding whether I'm worth listening to.

- More depth than a reach post. Show how and why, not only what.
- Earn trust with proof, examples and stories from the raw input. Show the work and the numbers.
- Useful enough that the reader would come back to it.
- Don't sell anything.""",
    "BOF": """\
# Funnel stage: bottom of funnel (BOF)

The goal is conversion: the reader already trusts me and is ready to act.

- The most detailed stage. Specifics: what it is, who it's for, what they get, what it changed. Use only what the raw input gives.
- One clear CTA, with the exact next step.
- Specific beats hype. No pushy promotion: the post still gives value to someone who never acts on the CTA.""",
}

FUNNEL_CTA: dict[PromptFunnel, str] = {
    "TOF": """\
## CTAs that fit top of funnel

- Best: no CTA at all (the post is the CTA); a reply to a specific question; a share ("Send this to a founder who..."); a follow only when there is a series to follow for.
- Avoid: links, DMs, "like and repost".""",
    "MOF": """\
## CTAs that fit middle of funnel

- Best: a bookmark on a utility post ("Save this for your next..."); a reply with their own experience; a follow for the series; a native click (a thread, an X Article, my pinned post).
- Avoid: external links, selling.""",
    "BOF": """\
## CTAs that fit bottom of funnel

- Best: a DM with a keyword ("DM me 'harness' and I'll send it"); a sign-up or waitlist (link in {link_place}); a buy (link in {link_place}); a lead magnet, used sparingly.
- Avoid: vague asks ("check it out").""",
}


# levers: the combination that drives this action on X. cta: the cta_type the sketch should use.
ACTION: dict[DesiredAction, dict[str, str]] = {
    "dwell_time": {
        "levers": "curiosity_gap + payoff + proof",
        "cta": "none",
        "text": """\
I want the reader to stop and read the whole post.

- Open a loop in the hook and close it late, not in line two. Each line earns the next one.
- No dead lines: cut anything the reader could skip without losing the thread.
- No explicit ask. Close on the takeaway.""",
    },
    "reply": {
        "levers": "surprise + identity",
        "cta": "reply",
        "text": """\
I want the reader to reply.

- Take the stance the raw input holds, and state it plainly enough that a reader can agree or push back.
- Leave room for them: don't cover every angle and every objection yourself.
- Close with one specific question they can answer from their own experience in a line. It must be about this post's idea, and easy to answer.""",
    },
    "bookmark": {
        "levers": "curiosity_gap + payoff + proof",
        "cta": "bookmark",
        "text": """\
I want the reader to bookmark the post.

- Make it worth coming back to: something they will use later (steps, a rule, a checklist, numbers), not something to nod at.
- Make the useful part easy to find again when they reopen it.
- Close by naming the exact future moment they'll need it ("Save this for the next time you..."). If that line would feel forced, close on the takeaway and let the usefulness do the work.""",
    },
    "repost": {
        "levers": "surprise + identity",
        "cta": "none",
        "text": """\
I want the reader to repost it.

- People repost what they'd be proud to have said: a line that puts words to what their group already feels.
- Make at least one line stand on its own when read out of context.
- Never ask for the repost. Close on the takeaway, stated plainly.""",
    },
    "share": {
        "levers": "identity + payoff",
        "cta": "share",
        "text": """\
I want the reader to send the post to someone.

- Write it so a specific person comes to mind: the reader should think "X needs to see this".
- Name who it is for.
- The closer can point at that person ("Send this to a founder who..."). Skip it if it would feel forced.""",
    },
    "follow": {
        "levers": "proof + vulnerability (+ curiosity_gap)",
        "cta": "follow",
        "text": """\
I want the reader to follow me.

- Show who I am and what I'm doing, from the positioning and the raw input: the post is a sample of what following me gets them.
- Give the reason to follow: what I keep posting about, or what comes next. Tease it only if the raw input or positioning supports it.
- Never write "follow for more". Give the reason and let them decide.""",
    },
    "trust": {
        "levers": "proof + vulnerability (+ curiosity_gap)",
        "cta": "none",
        "text": """\
I want the reader to trust me.

- Show the work: what I did, what happened, the real numbers, including the bad ones.
- Admit what went wrong or what I still don't know, when the raw input says so.
- No ask at all. An ask here costs trust. Close on the honest takeaway.""",
    },
    "click": {
        "levers": "payoff + proof + loss_aversion",
        "cta": "click",
        "text": """\
I want the reader to click through to something.

- Say exactly what they get on the other side and why it's worth the click.
- The post still gives real value on its own.
{click_link}""",
    },
    "DM": {
        "levers": "payoff + proof + loss_aversion",
        "cta": "DM",
        "text": """\
I want the reader to DM me.

- Give them a concrete reason and a low-effort way: one keyword to send, and what I send back.
- The post is complete without the DM. The DM gets them the extra thing, not the value withheld.""",
    },
    "sign-up": {
        "levers": "payoff + proof + loss_aversion",
        "cta": "sign-up",
        "text": """\
I want the reader to sign up.

- Say what they sign up for, who it's for and what they get, in specifics from the raw input.
{link}""",
    },
    "buy": {
        "levers": "payoff + proof + loss_aversion",
        "cta": "buy",
        "text": """\
I want the reader to buy.

- Say what it is, who it's for, what it changes for them, and the price if the raw input gives it.
- Proof before the ask.
{link}""",
    },
}


@dataclass(frozen=True)
class LinkPlacement:
    """Where an external link goes, in the words of the sections that place one."""

    external_link: str
    link_example: str
    link_place: str
    click_link: str
    link: str


# A single post's link goes in its first reply (ADR 0027).
POST_LINKS = LinkPlacement(
    external_link="- Never put an external link in the post. It goes in `first_reply`. Native links (a thread, an X Article, my profile) are fine in the post.",
    link_example="Repo's in the first reply. It's free.",
    link_place="the first reply",
    click_link="- A native link (a thread, an X Article, my profile, my pinned post) can sit in the post. An external link goes in `first_reply`, and the post's closer says it is there.",
    link="- The link goes in `first_reply`. The post's closer says it is there.",
)

# A Thread has no first reply: its link goes in its last Part.
THREAD_LINKS = LinkPlacement(
    external_link="- An external link goes in the last part, and the closer says what it leads to. A thread has no first reply. Native links (another thread, an X Article, my profile) are fine in any part.",
    link_example="Everything above is in the repo. It's free.",
    link_place="the last part",
    click_link="- A native link (another thread, an X Article, my profile, my pinned post) can sit in any part. An external link goes in the last part, and the closer says what it leads to.",
    link="- The link goes in the last part, and the closer says what it leads to.",
)


def placed(section: str, links: LinkPlacement) -> str:
    """`section` with its link placeholders filled in."""
    return section.format(**asdict(links))


MEDIUM_TARGET = "350 to 600"
LONG_TARGET: dict[PromptFunnel, str] = {
    "TOF": "400 to 900",
    "MOF": "700 to 1,600",
    "BOF": "900 to 2,000",
}


def _format_section(plan: Plan, char_limit: int) -> str:
    if effective_length(plan) == LENGTH_SHORT:
        return f"""\
# Format: short post

- At most {min(SHORT_LIMIT, char_limit)} characters as X counts them (a link counts as 23). This is a hard limit: count before you answer.
- The whole post shows in the feed. There is no "Show more".
- The hook IS the post. Line one must be strong enough to stand alone.
- Every word is paid for. One idea, no setup, no recap."""
    if plan.length == "medium":
        return f"""\
# Format: medium post

- A single post of middle length (X Premium): longer than a short post, much shorter than a long one. Not a thread.
- Aim for {MEDIUM_TARGET} characters as X counts them (a link counts as 23). Hard limit: {min(MEDIUM_LIMIT, char_limit)} characters: count before you answer.
- Only the first ~{PREVIEW_CHARS} characters show in the feed before "Show more". The hook and the one or two lines after it must make the reader tap it.
- Room for the hook, one developed point with its proof, and the closer. Each part of the structure gets a few lines at most: no second point, no setup, no recap.
- Never pad to reach the length. Go shorter when the raw input doesn't hold enough."""
    return f"""\
# Format: long post

- A single long post (X Premium). Not a thread.
- Only the first ~{PREVIEW_CHARS} characters show in the feed before "Show more". The hook and the one or two lines after it must make the reader tap it. Don't spend them on setup.
- Aim for {LONG_TARGET[PROMPT_FUNNELS[plan.funnel]]} characters. Go shorter when the raw input doesn't hold enough for that: never pad. Hard limit: {min(LONG_LIMIT, char_limit):,} characters.
- Short paragraphs and white space. The reader should be able to scan it."""


STRUCTURE: dict[Structure, str] = {
    "one_line": """\
# Structure: one line

- The post is one line: one or two sentences, no line break.
- The hook is the whole post, so the line must carry the core idea and the takeaway by itself.
- No separate closer and no separate CTA line. If the desired action needs an ask, the line itself is the ask (for a reply, the line can be the question).""",
    "few_lines": """\
# Structure: a few lines

- 2 to 5 short lines.
- Line 1: the hook.
- Middle: one to three lines that pay the hook off.
- Last line: the closer.""",
    "hook_list_closer": """\
# Structure: hook, list, closer

- Hook: says what the list is and why it's worth reading. If it carries a number, the number equals the number of items.
- A short line that leads into the list, when the hook doesn't already do it.
- The list: one item per line or short paragraph. Each item stands on its own and is concrete. Lead each item with the point, then at most a line of why or how.
- Only items the raw input gives. Don't pad the list to reach a round number. Put the strongest item first.
- Items differ in length and shape. Don't make them rigidly parallel.
- Closer.""",
    "hook_problem_insight_closer": """\
# Structure: hook, problem, insight, closer

- Hook.
- Problem: the situation or mistake the reader recognises as theirs. Make them feel it in a few lines, in their words.
- Insight: what I found or figured out, with the proof from the raw input. This is the core idea and the bulk of the value.
- Closer.""",
    "hook_story_insight_closer": """\
# Structure: hook, story, insight, closer

- Hook: drop the reader into the story or its most surprising moment.
- Story: what happened, in the plain order it happened, first person, with the concrete details from the raw input. Only what the reader needs to get to the insight. No scene-setting, no invented dialogue.
- Insight: what the story showed me, stated once.
- Closer. No moral bolted on.""",
    "hook_playbook_closer": """\
# Structure: hook, playbook, closer

- Hook: the outcome the playbook gets, with proof if the raw input has it.
- A short line that leads into the steps.
- Playbook: the steps the reader can copy, in order, one per line or short paragraph. Each step starts with a verb and says exactly what to do. Add the why only when it changes how they'd do it.
- Only the steps the raw input gives. If it gives a method without clean steps, break the method into the fewest steps that are still true to it.
- Closer.""",
}


def prompt_format(plan: Plan) -> str:
    """The Plan's `format` as the prompts name it: the Length of a single post, or `thread`."""
    return FORMAT_THREAD if plan.format == FORMAT_THREAD else effective_length(plan)


def effective_length(plan: Plan) -> Length:
    """one_line and few_lines are short by definition, whatever the Length says."""
    if plan.structure in ("one_line", "few_lines") or plan.length is None:
        return LENGTH_SHORT
    return plan.length


def plan_structure(plan: Plan) -> Optional[Structure]:
    """The Plan's structure, or None when its Format has none such: a short post's, switched to a Thread."""
    if plan.format == FORMAT_THREAD and plan.structure not in THREAD_STRUCTURES:
        return None
    return plan.structure


def length_for_limit(char_limit: int) -> Length:
    """The longest Length whose v5 limit the account's limit holds, or short."""
    if char_limit >= LONG_LIMIT:
        return "long"
    if char_limit >= MEDIUM_LIMIT:
        return "medium"
    return LENGTH_SHORT


def char_limit_for_plan(plan: Plan, char_limit: int) -> int:
    """The post's hard limit: v5's for its Length, or the account's when that is lower."""
    v5_limit = {"short": SHORT_LIMIT, "medium": MEDIUM_LIMIT, "long": LONG_LIMIT}
    return min(v5_limit[effective_length(plan)], char_limit)


def action_section(plan: Plan, links: LinkPlacement) -> str:
    action = ACTION[plan.desired_action]
    lines = [
        f"# Desired action: {plan.desired_action}",
        "",
        placed(action["text"], links),
        "",
        f"Levers that drive this action on X: {action['levers']}. Start from this combination. "
        "Swap a lever only when the raw input can't support it honestly (no proof lever without a number, "
        "name or result in the raw input; no vulnerability lever without a real mistake or doubt in it).",
    ]
    if plan.desired_action not in FUNNEL_ACTIONS[plan.funnel]:
        lines += [
            "",
            f"Note: this action is unusual for {PROMPT_FUNNELS[plan.funnel]}. Keep the depth and tone of the funnel stage, "
            "still aim the post at this action, and make any ask as light as it can be.",
        ]
    return "\n".join(lines)


def closer_section(plan: Plan, links: LinkPlacement) -> str:
    action = ACTION[plan.desired_action]
    if plan_structure(plan) == "one_line":
        chosen = (
            "For this post: there is no separate closer or CTA line (one-line structure). "
            f'`cta_type` is "{action["cta"]}" only if the line itself makes that ask, otherwise "none".'
        )
    elif action["cta"] == "none":
        chosen = (
            f"For this post: the desired action is {plan.desired_action}, which is earned by the post and never asked for. "
            'Close on the takeaway. `cta_type` is "none".'
        )
    else:
        chosen = (
            f'For this post: the desired action is {plan.desired_action}, so the CTA is "{action["cta"]}", '
            "written the way the desired-action section says. "
            'If the raw input and positioning give nothing real to ask for, or the ask would feel forced, close on the takeaway and set `cta_type` to "none".'
        )
    funnel_cta = placed(FUNNEL_CTA[PROMPT_FUNNELS[plan.funnel]], links)
    cta_rules = placed(CTA_RULES, links)
    return "\n\n".join(["# The closer and the CTA", CLOSER_RULES, funnel_cta, cta_rules, chosen])


def writing_guide(plan: Plan, char_limit: int) -> str:
    """Everything a writer needs to write this post, tailored to the Plan's choices."""
    return "\n\n".join(
        [
            CONTENT_RULES,
            GOOD_POST,
            FUNNEL[PROMPT_FUNNELS[plan.funnel]],
            action_section(plan, POST_LINKS),
            _format_section(plan, char_limit),
            STRUCTURE[plan.structure],
            HOOK,
            OPENING,
            closer_section(plan, POST_LINKS),
            RHYTHM,
            NEVER_ADD,
        ]
    )
