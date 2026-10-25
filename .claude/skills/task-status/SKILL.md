---
name: task-status
description: Show the chat's goal in one sentence, then its task status as a checklist with clock times — completed steps with start–end time and duration, the current step with how long it has run, and planned steps with an estimated duration. Use when the user types /task-status or asks for status, progress, or "your tasks checkboxed with time". Also usable by subagents to report their own steps.
---

# /task-status — timed task checklist

State the chat's goal in one sentence, then report every step of the current
work (yours, and those of any subagents you started) as a checklist with real
clock times, then keep timing every step for
the rest of the session.

## 1. Get the current time

Run `date` once; never guess the time:

```bash
env ${STATUS_TZ:+TZ=$STATUS_TZ} date '+%H:%M %Z'
```

`STATUS_TZ` (an IANA zone such as `Europe/Stockholm`) overrides the machine's
zone; cloud containers run in UTC, so set it in the cloud environment's
variables. If the user has told you their time zone in this conversation, use
that zone. Use the same zone for every time you show.

## 2. Build the list

Take the steps from the task list (TaskCreate/TaskUpdate or TodoWrite) if one
exists, otherwise from the work done so far in this conversation plus the plan
for what is left. Include steps that subagents ran, labelled with the agent.

For each step, use the start and end times you recorded when the step started
and ended (see section 5). Format:

| State | Format |
| --- | --- |
| Completed | `Step text (HH:MM–HH:MM, N min)` |
| In progress | `Step text (since HH:MM, N min so far)` |
| Planned | `Step text (est. ~N min)` |
| Blocked | `Step text (blocked since HH:MM: reason)` |

- Duration is end minus start in whole minutes; a step under a minute is `0 min`.
  At 60 minutes or more, write `1 h 25 min`.
- Planned estimates come from how long similar steps took in this session; when
  there is nothing to compare with, give your best estimate and keep the `~`.
- When a time was not recorded, never invent it. Write `(time not recorded)`,
  or derive it from evidence you have (a timestamp in a log, a job's start time,
  a commit time) and mark it `~` for approximate, e.g. `(~17:40–17:52, ~12 min)`.

## 3. Write the goal

Start the output with the chat's GOAL: one sentence, at most 200 characters,
saying what the user wants this chat to achieve (the outcome, not the current
step). Take it from the user's request and any later change of direction they
gave. Keep it the same between calls unless the user changed the goal. If the
goal is unclear, write your best reading and end it with `(assumed)`.

## 4. Output it in both places

1. **Task list UI**: update the task subjects (TaskUpdate, or TodoWrite) so each
   one carries its time suffix, completed steps marked completed, the current
   step in progress. This renders as the checklist with ticks and circles.
2. **Chat message**: print the same list as a Markdown checklist, because some
   clients (e.g. mobile) do not show the task list panel:

```markdown
**Goal:** Deploy project005 on the spider factory and verify Scenario 3 live before any deletion.

**Status at 18:00 CEST** — 2 of 6 done, 15 min elapsed, ~40 min left

- [x] Find spider's layout and deploy path (17:45–17:59, 14 min)
- [x] Start the API on a spider worktree (17:59–18:00, 1 min)
- [ ] ▶ Add project005 configuration, steps 3.1–3.2 (since 18:00, 0 min so far)
- [ ] Deploy project005 and follow the job (est. ~15 min)
- [ ] Run Scenario 3 checks live (est. ~15 min)
- [ ] Report and ask before deleting, Scenario 4 (est. ~5 min)
```

The goal line comes first. The status line gives the current time, done/total, time elapsed since the first
step started, and the sum of the remaining estimates. Add one line under the
list only for a blocker or a decision the user must make; nothing else.

## 5. Keep timing from now on

Invoking this skill turns timing on for the rest of the session:

- When a step starts, run the `date` command above and put `(since HH:MM)` in
  its task subject.
- When it completes, run `date` again, replace the suffix with
  `(HH:MM–HH:MM, N min)` and mark it completed, before starting the next step.
- Whenever you show progress (checkbox a step done and start the next one),
  show the times, even when the user did not type /task-status.
- When you start a subagent, ask it to report each of its steps with start and
  end times in this same format, and include its steps in your list.

## When you are a subagent

If you were started by another agent and asked for status, return only the
goal line (your own task's goal) and the Markdown checklist from section 4
(with times for your own steps) so the parent
can merge it into its list.
