# The demo, step by step: two calls with the whole crew

You play both people, alone, in a quiet room.

- **Your phone is Sunita**, the hirer. Real WhatsApp, and the calls in the phone's browser.
- **The laptop is Ramesh**, the worker. His WhatsApp is the dashboard's "Second phone" panel. His calls are links opened in the laptop's browser.
- **The big screen shows the dashboard** (`http://localhost:8000/dashboard`) the whole time: conversation, checklist, fact graph, Gawah's crew in lanes along the bottom, the witness chain.

The story: Day 1, the deal call and the call-backs, version 1 of the agreement, the advance screenshot. Day 5, a second call where Ramesh remembers the total wrong and both agree a change by voice; version 2 arrives. Day 7, the work is done, and Gawah reminds Sunita of the balance. In the room it all happens in about 35 minutes.

It uses about 45 LiveKit participant-minutes and two of the dozen Sage2 calls a month. Rehearse it with `tools/dry_run.py` (no person) first; then do it once, properly.

The lines are in `fixtures/demo/demo_call_1.json` and `demo_call_2.json`; the tables below are the same lines. `tools/dry_run.py` plays exactly these.

## Before you start

- Earphones in the laptop. Phone volume all the way down: you hear Gawah and "Ramesh" through the laptop's earphones. A phone loudspeaker would be picked up by the laptop's microphone and taken for Ramesh.
- Phone and laptop at opposite ends of the room, at least 3 metres apart. Speak each person's lines close to that person's device, at a normal voice.
- Phone: screen timeout 5 minutes or more. The phone mutes its microphone when the screen locks or the call page goes to the background.
- Put `fixtures/demo/advance-5000.png` (a ₹5,000 UPI payment screen) in the phone's photos: AirDrop it, or mail it to yourself.
- Phone hotspot ready, in case the laptop's network drops.
- WhatsApp sandbox membership lapses on 24 November. If Gawah never answers, send the sandbox join message (`join <code>`) again first.
- **Real WhatsApp messages to your phone are refused on this Twilio trial** (error 21654). What you send reaches Gawah; what Gawah sends you does not arrive. Every message Gawah sends you is on the dashboard, in the "Real phone" panel, so wherever a step says "Phone: you get ...", look there. "When the phone gets nothing" at the end says how to open your links.

## How to talk to Gawah

- **Wait for Gawah to finish.** Talking over Gawah stops it mid-sentence. Where a table says **Wait for Gawah**, stay quiet until it has finished, up to the time given.
- One line, then about a second's pause, then the next. Gawah needs about 5 seconds after a line before it can speak (the line is written down about 2 seconds after you stop, then it decides and finds its words), so it gets in only where you wait for it. That is why the waits are marked.
- When Gawah has finished, give it a few more seconds before the next line: it often goes on after a short pause (a clip, then a question).
- Say "Gawah ji" clearly, as two words. In the dry run a generated voice's "Gawah ji" was written down as "दबा जी", and Gawah never knew it was asked.
- Say the numbers as written ("pachees hazaar", "baees hazaar"). Look at the dashboard checklist, not the transcript, to see what was understood: the transcript is in Devanagari and not exact.

---

## Day 1

### 1. Start everything (laptop)

```
uv run python tools/demo.py
```

**You should see** six lines marked `OK` (OpenAI, Sage2, LiveKit, Twilio, S3, Chrome), then a box with the dashboard address and the webhook address.

**If not:**
- `S3 ... EXPIRED`: the AWS keys are temporary. Put new ones in `.env`, all three together, and start again.
- `LiveKit ... room(s) open`: an old room is still costing minutes. Delete it in the LiveKit dashboard, or Ctrl-C and start again.
- `WARN this laptop cannot find the public address yet`: wait a minute before opening any link on the laptop, and do not keep reloading. Or open the same link with `http://localhost:8000` in place of the `https://....trycloudflare.com` part: it is the same page.
- Anything else `FAIL`: the reason is on the line. Fix it before going on.

### 2. Point Twilio at this run (laptop, Twilio console)

The address changes on every start.

1. Twilio console > Messaging > Try it out > Send a WhatsApp message > **Sandbox settings**.
2. "When a message comes in": paste the webhook address from the box (it ends in `/whatsapp/webhook`). Method `POST`. Save.

### 3. The dashboard on the big screen (laptop)

Open `http://localhost:8000/dashboard`. **You should see** "No deal yet".

### 4. Say hello (phone)

Send `hi` to the sandbox number.

**Dashboard, "Real phone" panel:** your `hi`, then Gawah's "Namaste, main Gawah hoon. Deal shuru karne ke liye doosre vyakti ka mobile number bhejiye."

**If the dashboard shows nothing:** the webhook address in Twilio is wrong or not saved (step 2). Twilio console > Monitor > Logs > Errors shows what Twilio got back.

### 5. Start the deal (phone)

Send Ramesh's number: exactly what is in the "Second phone" panel's Number box, with the `+91` (by default `+910000000002`). Without the `+91` it does not start a deal.

**You should see:**
- Dashboard: a new deal; the people strip shows Sunita (hirer) and "Worker".
- "Real phone" panel: "Namaste! Gawah aapki deal ka gawah rahega. Call ke liye yeh link kholiye: https://.../hirer".
- "Second phone" panel: "... aapke saath kaam ki deal pakki karna chahte hain ... link kholiye: https://.../worker".

### 6. Join call 1

1. Laptop: click Ramesh's link in the "Second phone" panel. Press the green **Judiye** button and allow the microphone.
2. Phone: open your link (see "When the phone gets nothing" for how). Press the green **Judiye** button and allow the microphone. If the WhatsApp in-app browser blocks the microphone, open the link in Chrome.

**You should see:** both pages say you are connected. Within about 5 to 20 seconds (it waits to hear both of you, at most 15 seconds) Gawah says: "Namaste. Main Gawah hoon. Yeh call record ho rahi hai ... Aap dono, kripya ek-ek karke apna naam bataiye aur kahiye ki aap sehmat hain." The dashboard header says "On call 1".

**If Gawah never speaks:** look in the server log for `Gawah has no voice on this call`. The call still works without the voice; go on.

### 7. Call 1: the deal

| # | Device | Say |
|---|---|---|
| 1 | Phone (Sunita) | Main Sunita hoon. Main sehmat hoon. |
| 2 | Laptop (Ramesh) | Main Ramesh, painter. Main bhi sehmat hoon. |
| 3 | Phone | Mujhe apna flat paint karwana hai. Two BHK hai, Indirapuram mein, third floor pe. |
| 4 | Laptop | Do coat aur putty ka touch-up, material ke saath pachees hazaar lagega madam. |
| 5 | Phone | Pachees hazaar bahut zyada hai. Mera budget twenty thousand ka hai. |
| 6 | Laptop | Madam bees mein nahi ho payega, labour hi teen aadmi ka hai. Chalo baees hazaar final kar lo. |
| 7 | Phone | Theek hai, twenty two thousand done. Lekin material aapka hoga, upar se koi extra charge nahi. |
| 8 | Laptop | Haan theek hai. |
| 9 | Laptop | Advance kitna doge madam? Material lene ke liye paanch hazaar toh pehle chahiye. |
| 10 | Phone | Theek hai, paanch hazaar advance. |
| 11 | Laptop | Ji madam, theek hai. |
| 12 | Phone | Chalo theek hai. Kaam kab se start karoge? |
| | | **Wait for Gawah, up to 25 seconds.** You moved on to dates without saying when the balance is paid: Gawah asks Sunita. If it does not, go on: the next line answers it anyway. |
| 13 | Phone | Baaki paisa kaam poora hone ke din de dungi. |
| 14 | Laptop | Ji madam, theek hai. |
| 15 | Laptop | Agle somvaar se shuru kar denge, subah nau baje tak pahunch jayenge. |
| 16 | Phone | Aur khatam kab tak hoga? 15 tareekh ko mere ghar pe guests aa rahe hain. |
| 17 | Laptop | Paanch din ka kaam hai madam. Shukravaar tak finish, pandrah tareekh se pehle ho jayega. |
| 18 | Phone | Pakka? |
| 19 | Laptop | Pakka. |
| 20 | Laptop | Late hua to har din ka paanch sau kaat lena. |
| 21 | Phone | Theek hai, paanch sau kaat lena. |
| 22 | Laptop | Gawah ji, advance kitna tay hua tha? |
| | | **Wait for Gawah, up to 25 seconds.** "Haan ji, ek second", then the advance: 5,000. |
| 23 | Phone | Chalo, sab tay ho gaya. Dhanyavaad Ramesh ji. |
| 24 | Laptop | Ji madam, dhanyavaad. |
| | | **Wait for Gawah, up to 45 seconds.** It reads the terms back and asks you both to say haan. |
| 25 | Phone | Haan, sab sahi hai. |
| 26 | Laptop | Haan ji, sab sahi hai. |

Then press **Call chhodein** on both.

**On the dashboard during the call:** each line under its speaker; the checklist filling in (work, amount 22,000, advance 5,000, dates, balance, late); the fact graph growing, with 25,000 and 20,000 as offers and 22,000 as agreed; the crew's lanes (Ears, Scribe, Memory, Judge, Floor, Gawah) each saying what it just did. When Gawah speaks, "Why Gawah spoke" says why.

**If Gawah does not ask about the balance in 30 seconds:** go on to line 18 anyway, and note it. **If it does not answer line 22:** say it once more, a little closer to the laptop. **If it does not read the terms back:** go on; the call-backs read every term to each of you.

**Line 12, say "kab se" clearly.** Your recording of it was written down as "काम कल से स्टार्ट करो" (start tomorrow) in both dry runs.

**If a line appears twice, once under each name,** the far microphone heard you: move the devices further apart next time.

### 8. The call-backs, one person at a time

About 3 seconds after you both leave, each of you gets a call-back link ("Gawah aapse akele mein deal ki sharten confirm karna chahta hai").

1. Phone: open your call-back link. Press **Baat shuru karein**.
2. Gawah reads each agreed term, one at a time. After each, say **"haan, sahi hai"**.
3. It ends by itself, in 2 to 3 minutes.

Then the same on the laptop, from Ramesh's call-back link in the "Second phone" panel.

**You should see:** after each call-back, the dashboard header says "Sunita confirmed the terms" (then Ramesh). **If Gawah keeps waiting:** say "haan" a little louder, closer to the device.

### 9. The agreement, version 1

About 30 to 60 seconds after the second call-back ends.

**You should see**, in both phone panels: "Aapki deal ka contract taiyaar hai. Neeche PDF aur awaaz mein summary hai.", the PDF, and a voice note. The Clerk's lane says "contract v1 written". The header gets "Open the contract".

**If nothing comes in 2 minutes:** look in the server log for `CONTRACT NOT WRITTEN`; the reason follows. **If the line says "par uski file abhi nahi bhej paaye":** no link could be made for the PDF; check the S3 line from step 1.

### 10. The advance screenshot (phone)

Send the picture `advance-5000.png` to the sandbox number, with the words `Advance bhej diya`.

**You should see**, within about 15 seconds:
- "Real phone" panel: "Record mein likh liya: ₹5,000 advance, transaction id 632514790517, ..." then "Advance ₹5,000 mil gaya. Baaki ₹17,000 kaam ke baad."
- "Second phone" panel: "Advance ₹5,000 mil gaya. Baaki ₹17,000 kaam ke baad."
- Fact graph: a payment of 5,000 under the advance, with its proof. The Sentinel's lane says the advance stands.

A screenshot of a payment is proof on its own, so nobody is asked to confirm it.

**If it says "₹5,000 pehle se record mein hai" and "Baaki ₹12,000":** memory took something said on the call as the advance already paid, and counted it twice. In the dry run that was "Paanch hazaar advance main kal GPay kar dungi", which is why line 10 no longer promises to pay. Say the call lines as written. The dashboard's fact graph shows the payment under the advance with the call line it came from.

---

## Day 5

### 11. Ramesh opens a new call (laptop)

Click Ramesh's **call** link again (the first one, from step 5). The page says the call is over; press **Phir se baat karein**.

**You should see:**
- "Real phone" panel: "... aapse deal par phir se baat karna chahte hain. Call ke liye yeh link kholiye: https://.../hirer".
- Dashboard: the Sentinel's lane, "call 2 opened by the worker: told the hirer".

Phone: open your call link (the same one as on day 1) and press **Phir se baat karein**. Gawah greets you both by name and asks you to say your names again. The header says "On call 2".

### 12. Call 2: the wrong total, and a change

| # | Device | Say |
|---|---|---|
| 1 | Laptop (Ramesh) | Main Ramesh. Main sehmat hoon. |
| 2 | Phone (Sunita) | Main Sunita. Main bhi sehmat hoon. |
| 3 | Laptop | Madam, aadha kaam ho gaya. Total pachees hazaar tay hua tha na? |
| | | **Wait for Gawah, up to 45 seconds.** It says the amount was agreed at 22,000 by both on day 1, plays that moment of call 1 in your own voices, and asks which you mean. |
| 4 | Phone | Nahi, baees hazaar hi tay hua tha. |
| 5 | Laptop | Haan ji, baees hi. Galti ho gayi. |
| 6 | Phone | Ek kaam aur hai. Balcony ki deewar bhi paint kar dijiye. |
| 7 | Laptop | Ho jayega madam. Uske do hazaar extra lagenge. |
| 8 | Phone | Theek hai, do hazaar extra. Total chaubees hazaar. |
| | | **Wait for Gawah, up to 45 seconds.** It may first play the 22,000 moment again (see below), then it says the change, 22,000 to 24,000, and asks you both to say haan. Answer only after it has asked. |
| 9 | Phone | Haan, mujhe manzoor hai. |
| 10 | Laptop | Haan ji, mujhe bhi manzoor hai. |
| | | **Wait for Gawah, up to 30 seconds.** It says the change holds: the total is now 24,000. |
| 11 | Phone | Theek hai Ramesh ji, bye. |
| 12 | Laptop | Namaste madam. |

Then **Call chhodein** on both.

**On the dashboard:** at line 3 a red contradiction link in the fact graph, from Ramesh's "25,000" to the 22,000 both agreed, with "Hear what was agreed"; Gawah's lane says it played the clip. At line 8 the change appears; when both have said haan, the amount reads 24,000 and the old 22,000 is marked replaced.

**At line 8, Gawah may first replay the 22,000 moment.** The brain takes the new total as a contradiction of the old one before Gawah has proposed the change. Wait it out: Gawah then proposes the change. Answer haan only after it has asked.

**If Gawah says it heard you both but "record mein final update nahi hai",** the yes was not recorded (it happened in the dry run, see the report). Each say once more, after Gawah is quiet: "Gawah ji, mujhe chaubees hazaar manzoor hai." A line with Gawah's name gets a turn that can record a yes.

**If Gawah says nothing at line 3 in 45 seconds:** go on and note it; the dashboard still shows the red link if the Scribe caught it. **If it never proposes the change:** say line 8 once more. **If it does not hear one "haan":** say it again.

### 13. The agreement, version 2

Both of you agreed the change on the call, so there is no call-back this time. Within about a minute both phone panels get the agreement again: version 2, with its change history (22,000 to 24,000, agreed by voice on call 2), the PDF and a voice note. The Clerk's lane says "contract v2".

If one of you did not say haan, that person gets a call-back link instead: do step 8 for them.

---

## Day 7

### 14. The work is done

1. "Second phone" panel (Ramesh): send `kaam poora ho gaya`.
2. "Real phone" panel: Gawah asks Sunita: 'Ramesh ji ne likha hai: "kaam poora ho gaya". Kya yeh sahi hai? Haan ya nahi likhiye.'
3. Phone: send `haan`.

**You should see**, in both panels: "Kaam poora ho gaya, dono ne confirm kiya. Deal ke hisaab se baaki ₹19,000."

### 15. The reminder

Wait about a minute (the Sentinel's delay, `SENTINEL_BALANCE_REMINDER_SECONDS`, 60 by default; set it in the shell before step 1 to change it).

**You should see:**
- "Real phone" panel: "Yaad dila raha hoon: kaam poora ho chuka hai, dono ne confirm kiya tha. Deal ke hisaab se ₹19,000 baaki hai."
- "Second phone" panel: "Gawah ne Sunita ji ko ₹19,000 baaki ki yaad dila di hai."

### 16. Stop

Ctrl-C in the runner's terminal. It stops the server and the tunnel, deletes any room this run opened, and prints `LiveKit rooms open now: none`. The run's database and server log stay in `runs/`.

---

## When the phone gets nothing

Twilio refuses every send to your phone on this trial, so you copy your links by hand. The dashboard shows everything Gawah sent you in the "Real phone" panel; your links are also Ramesh's with `hirer` in place of `worker`:

- Call (day 1 and day 5): Ramesh's call link from the "Second phone" panel, with the ending `/worker` changed to `/hirer`.
- Call-back: the same, with Ramesh's call-back link.
- The agreement: Ramesh's PDF link in the "Second phone" panel works for 15 minutes.

To get a link onto the phone: WhatsApp it to yourself from the laptop, or AirDrop it.

## Rehearsing without a person

```
uv run python tools/demo.py            # in one terminal
uv run python tools/dry_run.py         # in another: the whole story, simulated phones, headless browsers
uv run python tools/dry_run.py --from call2   # retry from call 2 on the latest deal
uv run python tools/dry_run.py --offline      # nothing outside: tests/offline.py in-process
```

It writes every event, each step with its time and result, and dashboard screenshots to `runs/dry-<time>/`.
