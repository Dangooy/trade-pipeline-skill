# Gate Pattern — AI Skill Access Control

A three-level gate model for controlling when an AI agent should pause and ask for human confirmation before executing an action.

## Three Gate Levels

| Level | Name | Trigger | AI Behavior |
|-------|------|---------|-------------|
| **0** | No gate | Read-only / local file generation | Execute directly, no confirmation |
| **1** | Preview & confirm | Sending to external systems (email/messages/approvals) | Show full draft → wait for user to say "confirm" / "send" |
| **2** | Double-check | Irreversible + high-impact (batch send/delete/submit) | Preview + impact scope + require explicit confirmation keyword |

## Level Behaviors

### Level 0 — Direct Execution
No extra steps. Generate file, report path and summary.

### Level 1 — Preview & Confirm
1. Generate draft/content
2. Show complete content to user (for email: recipients + subject + body)
3. Wait for explicit positive reply ("send", "confirm", "ok")
4. Only call the send API after confirmation
5. If user says "change" / "don't send" → stop, ask for feedback

### Level 2 — Double-Check
1. Generate draft/plan
2. Show impact scope summary:
   - How many objects affected (N emails / N messages / N approvals)
   - Irreversibility consequences
3. Require explicit confirmation keyword (e.g., "confirm submit", "confirm delete")
4. Ambiguous replies ("hmm", "okay") do not count — ask again

## Applying to Skills

When creating a new AI skill, declare its gate level:

- Produces only local files → Level 0
- Calls external APIs to send content → at least Level 1
- Sending is irreversible and affects multiple people/objects → Level 2

## Design Rationale

The cost of pausing to confirm is low (seconds). The cost of an unwanted action (wrong email sent, data deleted, approval submitted prematurely) can be very high. Gate levels encode this asymmetry into the skill system so that the AI agent follows consistent guardrails across all operations.
