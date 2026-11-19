# CI red on PR #121 head 3b2bdec: a real regression from the fix round

## The failure

CI `django-tests` (the re-run, run 44521803697 attempt 2, 17751 tests) has one failure:

```
FAIL: test_a_pinned_card_holds_it_with_the_hand_away (tests.test_marquee.TheStripsMeasuredTests)
  tests/test_marquee.py:1835 assertResumesFrom(held, _phase(got["samples"], 2, skip=0.1), "dh", "Escape")
AssertionError: 4395 not less than or equal to 10.5 : Escape: a jump from -4396.0 to -1.0 in 0.150 s
```

The scenario is `_pinned` (tests/test_marquee.py:952-971):
- a click pins the headband's `.dh-pop` card;
- the hand moves away (`__mq.away()`), and the strip holds;
- Escape closes the card, and the strip must resume from where it was held.

On 3b2bdec the strip instead jumps back to its start (pos 0). In `static/js/sv-marquee.js`, `refresh()` sets `s.pos = 0` when `!s.loop`, and it runs on a ResizeObserver hit on the track or the clip. So something resizes the strip, or re-measures it, at that Escape.

## Bisect (local, pinned Chromium 1243, CI faces via FONTCONFIG_FILE, `--parallel 1`, the single test)

| Tree | Result |
|---|---|
| 3b2bdec (branch head) | FAIL: `4396 not <= 9.50: a jump from -4396.0 to 0.0 in 0.133 s` (same as CI) |
| 304efaf (main merged, before the fixes) | OK |
| f3f6637 (before the main merge) | OK |
| 3b2bdec with `static/js/sv-frame.js` from 304efaf (`scratchpad/mqbisect/v_a`) | OK |
| 3b2bdec with `static/css/sv-frame.css` from 304efaf (`scratchpad/mqbisect/v_b`) | OK |

So it takes BOTH 3b2bdec's frame script AND its frame CSS. The scratch trees under `scratchpad/mqbisect/` are ready (each has had collectstatic run). The fix round's own runs reported `test_marquee: 331 OK` together with other modules. That ran before 3b2bdec's last state, or this single test passed by luck in a combined run. It fails 2 of 2 in isolation on 3b2bdec.

## Leading hypothesis (verify, do not trust)

The frame's new Esc (window-capture snapshot `escAt`, then it acts in the document's bubble) closes a panel on this Escape, even though the page's own pinned card had the key. That is B2's own bug in a new form: one Esc closes two things. The new dock CSS then turns that close, or the focus going back to a dock door, into a layout change that resizes the strip:
- m1: `.sv-dock .sv-door:hover { width: 32px; margin-left: -4px; padding-right: 4px }`, with transitions on `width`, `margin-left` and `padding-right`, where the old rule was a transform;
- m6: `.rail-head` gets `min-height: 41.3px`.

Ways the snapshot could miss:
- `cardOpen()` does not count the pinned `.dh-pop` at capture: check `svPin.current()`, and the POPS direct-body-child test;
- the capture listener throws or is skipped, so the bubble recomputes after `svPin` has already closed the card;
- a second synthetic Escape is dispatched.

Instrument the page and find out:
- log `escAt.other`;
- log what the frame closes, if anything, and where the focus goes;
- log the ResizeObserver entries for the dh strip at that Escape.

## What done looks like

- Root-cause it.
- Fix it in the PR's own code, keeping B2's guarantees: one Esc closes one thing, and the page's own card, menu or dialog goes first.
- Add a measured regression test in `tests/test_doors_measured.py`. It pins a headband card over an open panel, presses Esc once, and checks two things: only the card closes, and the strip does not jump. It must be red on 3b2bdec.
- Run `tests.test_marquee` in full with `--parallel 1` (both strips; all its scenarios), and `tests.test_doors_measured`.
- Run the modules the fix touches and the old-design guard.
- Commit, run the privacy scan, push. The next CI run replaces the spent re-run.
