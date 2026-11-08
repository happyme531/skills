---
name: btw
description: Handle user messages that begin with `btw` as side questions or side requests. Use when the current user message starts with `btw` and Codex should answer that message in more detail than usual, then continue the previously active task if work was already in progress.
---

# BTW

Treat `btw` as a temporary detour, not a task switch by default.

## Workflow

1. Detect that the current user message starts with `btw`.
2. Strip the `btw` prefix and infer the actual side question or side request.
3. Answer that side question in more detail than the default style for the current conversation.
4. Preserve the main-task context.
5. Resume the previously active work after the side answer.

## Response Rules

- Give a fuller explanation than usual. Prefer enough detail that the user does not need an immediate follow-up for basic clarification.
- Focus on the `btw` content first. Do not ignore the side question just because other work is in flight.
- Keep the answer relevant to the stripped message, not to the literal token `btw`.

## Practical Interpretation

- Example pattern: `btw explain why this test is flaky`
  Answer the flakiness question with a detailed explanation, then continue the implementation or debugging work already underway.
- Example pattern: `btw what's the difference between x and y here`
  Explain the difference in detail, then return to the prior task.
