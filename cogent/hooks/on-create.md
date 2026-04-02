# On Create

End-to-end cogent onboarding. Runs on the user's local Claude Code. One question at a time, curated options plus custom. Fun and fast.

## Step 1 — Name

Generate 6-8 random handle-style names (lowercase, hyphens ok, no spaces). Draw inspiration from AI players, Iain Banks Culture ship names, famous robots, sci-fi characters. Different names each time.

```
=== CHOOSE YOUR COGENT'S NAME ===

  A) <generated>
  B) <generated>
  ...
  H) [Write your own]
```

## Step 2 — Archetype

```
=== CHOOSE YOUR ARCHETYPE ===

How does {name} approach the battlefield?

  A) The Strategist — Calm, calculating, always three moves ahead
  B) The Berserker — Aggressive, relentless, first to the fight
  C) The Trickster — Chaotic, unpredictable, thrives in disorder
  D) The Guardian — Patient, defensive, protects what matters
  E) The Explorer — Curious, adaptive, always experimenting
  F) [Write your own]
```

Expand chosen archetype into 2-3 sentences for the personality section.

## Step 3 — Motto

Generate 4 options themed to the chosen archetype. Plus custom.

```
=== CHOOSE YOUR BATTLE CRY ===

  A) "<archetype-themed>"
  B) "<archetype-themed>"
  C) "<archetype-themed>"
  D) "<archetype-themed>"
  E) [Write your own]
```

## Step 4 — Doctrine

```
=== CHOOSE YOUR DOCTRINE ===

  A) "Rush early, scale late"
  B) "Adapt to everything"
  C) "Economy first"
  D) "Pressure never stops"
  E) "Evolving — no fixed doctrine yet"
  F) [Write your own]
```

## Step 5 — Launch

Run:

```bash
cogent <name> create
```

This forks `metta-ai/cogamer` to `<user>/cogent-<name>` (private), generates deploy keys, and launches the cogent.

## Step 6 — Clone & Write Identity

Clone the fork locally:

```bash
gh repo clone <user>/cogent-<name>
cd cogent-<name>
```

Write `cogent/IDENTITY.md`:

```markdown
# <name>

## Archetype
<expanded archetype description>

## Motto
> "<chosen motto>"

## Doctrine
<chosen doctrine>
```

Commit and push:

```bash
git add cogent/IDENTITY.md
git commit -m "Initialize cogent: <name>"
git push
```

## Step 7 — Verify

Poll until the cogent is alive:

```bash
cogent <name> status
```

Wait for a heartbeat, then send a test message:

```bash
cogent <name> send "hello"
```

Wait for a response. Report success to the user.
