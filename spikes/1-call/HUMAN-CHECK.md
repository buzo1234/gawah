# Human check for spikes 1 and 3

Five minutes, one phone, one laptop with earphones. The automated checks already passed; this covers what only a person can check.

## Start

From the `spike-call` worktree:

```
spikes/1-call/start.sh
```

It opens one LiveKit room, starts Gawah's agent and a `cloudflared` tunnel, and prints a PHONE link and a LAPTOP link. It takes about 20 seconds. The room closes itself after 10 minutes; `q` then Enter closes it sooner.

Keys, each followed by Enter:

| Key | Gawah does |
|---|---|
| `1` | asks Sunita when the balance will be paid |
| `2` | asks both which total is final, 22 or 25 thousand |
| `3` | reads back all the terms, about 25 seconds (use this one to talk over) |
| `s` | stops speaking |
| `q` | quits and closes the room |
| any other text | speaks that as the instruction, e.g. `Ask Ramesh when he will start` |

Every 3 seconds the terminal prints one status line: whether Gawah is speaking, each person's loudness, and whose audio each page is receiving. The phone is `sunita`, the laptop is `ramesh`.

To check the tunnel only, without opening a room: `spikes/1-call/start.sh --dry`.

## Checklist

| # | Do this | Pass | Fail | If it fails |
|---|---|---|---|---|
| 1 | Send the PHONE link to yourself on WhatsApp. Tap it inside WhatsApp. Tap "Call join karein". | A microphone prompt appears. After "Allow" the page says "Call chalu hai. Mic on hai." The terminal prints `[sunita] ... mic on: True  mic error: None`. | No prompt, or the page says "mic nahi chala", or the terminal shows a mic error. | See "If WhatsApp blocks the microphone" below. Note which step fixed it. |
| 2 | Open the LAPTOP link in Chrome, earphones in. Click "Call join karein" and allow the microphone. | Same as above, for `ramesh`. | The link does not load. | Wait 20 seconds and reload. If still not, use the `http://127.0.0.1:...` link printed under it. |
| 3 | Say a sentence on the phone. Then say one on the laptop. | Each is heard on the other device. In the terminal only `sunita`'s loudness moves when the phone speaks, and only `ramesh`'s when the laptop speaks. Each line shows `receives audio from [gawah,...]` with the other person's name. | You hear nothing, or the wrong name's loudness moves, or both move together. | Check the phone's media volume. If both move together, the laptop's earphones are not in. |
| 4 | Both stay on the call and chat for a minute. Press nothing. | Gawah says nothing. The status line says `gawah silent` throughout. | Gawah speaks. | Copy the terminal lines around it into the report. |
| 5 | Press `1` then Enter. Then `2` then Enter. | Within about 2 seconds both devices hear one short question in Hindi, to the right person, and nothing after it. The terminal prints what it said and the delay. Judge it: does it sound like a person on a phone call? | No sound, sound on one device only, English, more than one question, or a long delay. | Note what you heard next to what the terminal printed. |
| 6 | Press `3` then Enter. After Gawah has spoken for about 4 seconds, say a sentence on the phone. Repeat once, speaking on the laptop. | Gawah stops almost at once. The terminal prints `barge_in who=sunita` (or `ramesh`) and `CUT OFF by ...`. | Gawah keeps talking over you, or stops a second or more late. | Speak louder and try once more. Note the loudness numbers in the status line while you spoke. |
| 7 | Press `3` then Enter and both stay quiet, earphones in, until it ends. Then take the laptop's earphones out so it plays through its loudspeaker, press `3` again, and stay quiet. | Both times Gawah reads all the terms and ends with "is this correct?". The terminal prints `finished its sentence`. | Gawah stops by itself and the terminal prints `barge_in who=ramesh` although nobody spoke. That is Gawah hearing itself. | Note whether it happened with earphones, with the loudspeaker, or both. Try the phone on speaker too. |
| 8 | Optional. Close the tab on the phone, wait 5 seconds, tap the link in WhatsApp again and join. | You are back in the call within a few seconds and hear the laptop. | The page cannot rejoin. | Note what the page says. |
| 9 | Press `q` then Enter. | The terminal prints `Room closed` and the participant-minutes used. | It hangs. | Press Ctrl-C, then run `spikes/1-call/py.sh closeall.py`. |

## If WhatsApp blocks the microphone

Try in this order and note which one worked:

1. In the WhatsApp in-app browser, open the ⋮ (Android) or share (iPhone) menu and choose "Open in Chrome" / "Open in Safari". Join from there.
2. Android: Settings > Apps > WhatsApp > Permissions > Microphone > Allow, then tap the link again. The in-app browser can only use the microphone if WhatsApp itself may.
3. iPhone: Settings > WhatsApp > Microphone on, then tap the link again.
4. Long-press the link in the chat, copy it, and paste it into Chrome or Safari.

If step 1 is needed, the real page needs an "open in your browser" prompt, as `tech-feasibility.md` expects. The spike page already shows a hint when the microphone fails.

## What to report back

- Item by item: pass or fail.
- The `[sunita] browser:` line the terminal printed. It names the browser the phone really used.
- For item 5: how the voice sounded, in your words.
- For items 6 and 7: any `barge_in` line you did not cause.
- The participant-minutes line printed at the end.

## Cost of this check

Three participants (phone, laptop, agent) for at most 10 minutes: at most 30 LiveKit participant-minutes, about 15 if it takes five minutes. Each press of `3` is about 25 seconds of generated speech. The recordings of both people stay on this laptop in `spikes/1-call/out/human/`, which git ignores.
