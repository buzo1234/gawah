# A live run, step by step: two calls with the whole crew

You play both people, alone, in a quiet room.

- **Your phone is Sunita**, the hirer. Real WhatsApp, and the calls in the phone's browser.
- **The laptop is Ramesh**, the worker. His WhatsApp is the dashboard's "Second phone" panel (also its own page, `/dashboard/phone`). His call links open inside that panel.
- **The big screen shows the dashboard** (`http://localhost:8000/dashboard`) the whole time: the contract checklist, the knowledge graph with the witness chain's state above it, and Ramesh's phone. Another deal: press D, or add `?deal=<id>`.

The story: Day 1, the deal call and the call-backs, version 1 of the agreement, the advance screenshot. Day 5, a second call where Ramesh remembers the total wrong and both agree a change by voice; version 2 arrives. Day 7, the work is done, and Gawah reminds Sunita of the balance. In the room it all happens in about 35 minutes.

It uses about 45 LiveKit participant-minutes and two of the dozen Sage2 calls a month. Walk it through first with `tools/walkthrough.py` (no person); then do it once, properly.

The lines are in `fixtures/story/story_call_1.json` and `story_call_2.json`; the tables below are the same lines. `tools/walkthrough.py` plays exactly these.

## Before you start

- Earphones in the laptop. Phone volume all the way down: you hear Gawah and "Ramesh" through the laptop's earphones. A phone loudspeaker would be picked up by the laptop's microphone and taken for Ramesh.
- Phone and laptop at opposite ends of the room, at least 3 metres apart. Speak each person's lines close to that person's device, at a normal voice.
- Phone: screen timeout 5 minutes or more. The phone mutes its microphone when the screen locks or the call page goes to the background.
- Put `fixtures/story/advance-5000.png` (a ₹5,000 UPI payment screen) in the phone's photos: AirDrop it, or mail it to yourself.
- Phone hotspot ready, in case the laptop's network drops.
- **WhatsApp runs on Meta's test number** (`WHATSAPP_PROVIDER=meta` in `.env`; the setup is in `tools/META-SETUP.md`). Before you start:
  - Make a fresh access token on Meta's API Setup page and put it in `.env` (`META_WHATSAPP_TOKEN`): the temporary one lasts only a few hours.
  - Your phone must be on the test number's allowed list and in `VERIFIED_NUMBERS`.
  - Meta lets Gawah message a phone only within 24 hours of that phone's last message, so your `hi` in step 4 comes first. One run sends your phone about 25 messages, inside the free 1,000 a month.
  - Ramesh's "Second phone" is simulated, as before: nothing sent to it reaches Meta.
- **On Twilio instead** (`WHATSAPP_PROVIDER=twilio`): the sandbox membership lapses on 24 November (send `join <code>` again first), and Twilio's trial refuses every message to your phone (error 21654). Then open `http://localhost:8000/dashboard/phone?number=<your number>` wherever a step says your phone gets something, and see "When the phone gets nothing" at the end.

## How to talk to Gawah

- **Wait for Gawah to finish.** Talking over Gawah stops it mid-sentence. Where a table says **Wait for Gawah**, stay quiet until it has finished, up to the time given.
- One line, then about a second's pause, then the next. Gawah needs about 5 seconds after a line before it can speak (the line is written down about 2 seconds after you stop, then it decides and finds its words), so it gets in only where you wait for it. That is why the waits are marked.
- When Gawah has finished, give it a few more seconds before the next line: it often goes on after a short pause (a clip, then a question).
- Say "Gawah ji" clearly, as two words. In a test run a generated voice's "Gawah ji" was written down as "दबा जी", and Gawah never knew it was asked.
- Say the numbers as written ("pachees hazaar", "baees hazaar"). Look at the dashboard checklist, not the transcript, to see what was understood: the transcript is in Devanagari and not exact.

---

## Day 1

### 1. Start everything (laptop)

```
uv run python tools/run_live.py
```

**You should see** six lines marked `OK` (OpenAI, Sage2, LiveKit, Meta WhatsApp, S3, Chrome; Twilio in Meta's place on Twilio), then a box with the dashboard address and the webhook steps.

**If not:**
- `S3 ... EXPIRED`: the AWS keys are temporary. Put new ones in `.env`, all three together, and start again.
- `Meta WhatsApp ... FAIL` with code 190: the access token has expired. Make a new one and start again.
- `LiveKit ... room(s) open`: an old room is still costing minutes. Delete it in the LiveKit dashboard, or Ctrl-C and start again.
- `WARN this laptop cannot find the public address yet`: wait a minute before opening any link on the laptop, and do not keep reloading. Or open the same link with `http://localhost:8000` in place of the `https://....trycloudflare.com` part: it is the same page.
- Anything else `FAIL`: the reason is on the line. Fix it before going on.

### 2. Point WhatsApp at this run (laptop)

The address changes on every start. The box prints these steps with the address filled in.

On Meta: Meta's app dashboard > **WhatsApp > Configuration > Webhook > Edit**.
1. **Callback URL**: the webhook address from the box (it ends in `/whatsapp/webhook`).
2. **Verify token**: the value of `META_VERIFY_TOKEN` in `.env`.
3. **Verify and save.** The server log shows `GET /whatsapp/webhook?hub.mode=subscribe... 200`; a 403 means the two verify tokens differ. **Messages** must stay subscribed under Webhook fields.

On Twilio: Twilio console > Messaging > Try it out > Send a WhatsApp message > **Sandbox settings**; "When a message comes in": the webhook address, method `POST`, Save.

### 3. The dashboard on the big screen (laptop)

Open `http://localhost:8000/dashboard`. **You should see** "No deal yet".

### 4. Say hello (phone)

Send `hi` to Gawah's number (Meta's test number).

**You should see:**
- Phone: blue ticks on your `hi`, "typing…", then "Namaste, main Gawah hoon. Deal shuru karne ke liye doosre vyakti ka mobile number bhejiye."
- Dashboard, "Real phone" panel: both messages.

**If the dashboard shows nothing:** the webhook is wrong, not saved, or not subscribed to messages (step 2).

**If the dashboard shows it but the phone gets nothing:** the server log has `not sent to ***NNNN: meta http ... code ...`. Code 190: the token has expired. Code 131030: your phone is not on the test number's allowed list. `tools/META-SETUP.md` lists the rest.

### 5. Start the deal (phone)

Send Ramesh's number: exactly what is in the "Second phone" panel's Number box, with the `+91` (by default `+910000000002`). Without the `+91` it does not start a deal.

**You should see:**
- Dashboard: a new deal; the people strip shows Sunita (hirer) and "Worker".
- Phone: "Namaste! Gawah aapki deal ka gawah rahega. Call ke liye yeh link kholiye." with a **Call kholiye** button. The "Real phone" panel shows the same.
- "Second phone" panel: "... aapke saath kaam ki deal pakki karna chahte hain ... link kholiye: https://.../worker".

### 6. Join call 1

1. Laptop: click Ramesh's link in the "Second phone" panel. Press the green **Join** button and allow the microphone.
2. Phone: tap **Call kholiye**. Press the green **Join** button and allow the microphone. If the WhatsApp in-app browser blocks the microphone, open the link in Chrome.

**You should see:** both pages say you are connected. Within about 5 to 20 seconds (it waits to hear both of you, at most 15 seconds) Gawah says: "Namaste. Main Gawah hoon. Yeh call record ho rahi hai ... Aap dono, kripya ek-ek karke apna naam bataiye aur kahiye ki aap sehmat hain."

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

Then press the red **End** button on both.

**On the dashboard during the call:** the checklist filling in (work, amount 22,000, advance 5,000, dates, balance, late), each with the call time it was agreed at; the knowledge graph growing, with 25,000 and 20,000 as offers and 22,000 as agreed.

**If Gawah does not ask about the balance in 30 seconds:** go on to line 18 anyway, and note it. **If it does not answer line 22:** say it once more, a little closer to the laptop. **If it does not read the terms back:** go on; the call-backs read every term to each of you.

**Line 12, say "kab se" clearly.** Your recording of it was written down as "काम कल से स्टार्ट करो" (start tomorrow) in both test runs.

**If a line appears twice, once under each name,** the far microphone heard you: move the devices further apart next time.

### 8. The call-backs, one person at a time

About 3 seconds after you both leave, each of you gets a call-back: "Gawah aapse akele mein deal ki sharten confirm karna chahta hai. Yeh link kholiye." with a **Call kholiye** button.

1. Phone: tap **Call kholiye**. Press the green **Join** button.
2. Gawah reads each agreed term, one at a time. After each, say **"haan, sahi hai"**.
3. It ends by itself, in 2 to 3 minutes.

Then the same on the laptop, from Ramesh's call-back link in the "Second phone" panel.

**You should see:** after each call-back, the dashboard checklist notes "Sunita confirmed"; once both have, the terms read "Confirmed". **If Gawah keeps waiting:** say "haan" a little louder, closer to the device.

### 9. The agreement, version 1

About 30 to 60 seconds after the second call-back ends.

**You should see:**
- Phone: **Gawah-contract-v1.pdf**, captioned "Aapki deal ka contract, version 1. Awaaz mein summary neeche hai.", then a voice note. (On Twilio: a line, the PDF, and a voice note.)
- "Second phone" panel: the same, as text and links.
- Dashboard: the Clerk's lane says "contract v1 written". The header gets "Open the contract".

**If nothing comes in 2 minutes:** look in the server log for `CONTRACT NOT WRITTEN`; the reason follows. **If the line says "par uski file abhi nahi bhej paaye":** no link could be made for the PDF; check the S3 line from step 1.

### 10. The advance screenshot (phone)

Send the picture `advance-5000.png` to Gawah, with the words `Advance bhej diya` as its caption.

**You should see**, within about 15 seconds:
- Phone: a ✅ on your screenshot, then "Record mein likh liya: ₹5,000 advance, transaction id 632514790517, ..." and "Advance ₹5,000 mil gaya. Baaki ₹17,000 kaam ke baad."
- "Second phone" panel: "Advance ₹5,000 mil gaya. Baaki ₹17,000 kaam ke baad."
- Fact graph: a payment of 5,000 under the advance, with its proof. The Sentinel's lane says the advance stands.

A screenshot of a payment is proof on its own, so nobody is asked to confirm it.

**If it says "₹5,000 pehle se record mein hai" and "Baaki ₹12,000":** memory took something said on the call as the advance already paid, and counted it twice. In a test run that was "Paanch hazaar advance main kal GPay kar dungi", which is why line 10 no longer promises to pay. Say the call lines as written. The dashboard's fact graph shows the payment under the advance with the call line it came from.

---

## Day 5

### 11. Ramesh opens a new call (laptop)

Click Ramesh's **call** link again (the first one, from step 5). The page says the call ended; press **Call again**.

**You should see:**
- Phone: "Ramesh ji aapse deal par phir se baat karna chahte hain. Call ke liye yeh link kholiye." with a **Call kholiye** button.
- Dashboard: the Sentinel's lane, "call 2 opened by the worker: told the hirer".

Phone: tap **Call kholiye** and press **Call again**. Gawah greets you both by name and asks you to say your names again. The header says "On call 2".

### 12. Call 2: the wrong total, and a change

| # | Device | Say |
|---|---|---|
| 1 | Laptop (Ramesh) | Main Ramesh. Main sehmat hoon. |
| 2 | Phone (Sunita) | Main Sunita. Main bhi sehmat hoon. |
| 3 | Laptop | Madam, aadha kaam ho gaya. Total pachees hazaar tay hua tha na? |
| | | **Wait for Gawah, up to 45 seconds.** It says the record holds 22,000, not 25,000 (Ramesh said it on day 1 and Sunita agreed), and asks if you want to hear that recording. |
| 4 | Phone | Haan, sunaiye. |
| | | **Wait for Gawah, up to 30 seconds.** A short lead-in, then that moment of call 1 in your own voices. |
| 5 | Laptop | Haan ji, baees hi. Galti ho gayi. |
| 6 | Phone | Ek kaam aur hai. Balcony ki deewar bhi paint kar dijiye. |
| 7 | Laptop | Ho jayega madam. Uske do hazaar extra lagenge. |
| 8 | Phone | Theek hai, do hazaar extra. Total chaubees hazaar. |
| | | **Wait for Gawah, up to 45 seconds.** Both of you said 24,000, and it is still only a change: Gawah says the record holds 22,000 and 24,000 was said, and asks if you both want to change it, "Dono haan kahiye". Answer only after it has asked. |
| 9 | Phone | Haan, mujhe manzoor hai. |
| 10 | Laptop | Haan ji, mujhe bhi manzoor hai. |
| | | **Wait for Gawah, up to 30 seconds.** It says the change holds: the total is now 24,000. |
| 11 | Phone | Theek hai Ramesh ji, bye. |
| 12 | Laptop | Namaste madam. |

Then the red **End** button on both.

**On the dashboard:** at line 3 a red contradiction link in the fact graph, from Ramesh's "25,000" to the 22,000 both agreed, with "Hear what was agreed", and the checklist's amount says "Contradicted". At line 8 the change appears; the amount stays 22,000 until both have said haan to Gawah, then the checklist's amount reads "Changed" 24,000, and in the graph the old 22,000 is marked replaced.

**If nobody says "haan, sunaiye" at line 4,** Gawah does not play the recording: it plays it only on a yes, or when someone asks for it.

**If Gawah says it heard you both but "record mein final update nahi hai",** the yes was not recorded (it happened in a test run, see the report). Each say once more, after Gawah is quiet: "Gawah ji, mujhe chaubees hazaar manzoor hai." A line with Gawah's name gets a turn that can record a yes.

**If Gawah says nothing at line 3 in 45 seconds:** go on and note it; the dashboard still shows the red link if the Scribe caught it. **If it never proposes the change:** say line 8 once more. **If it does not hear one "haan":** say it again.

### 13. The agreement, version 2

Both of you agreed the change on the call, so there is no call-back this time. Within about a minute both of you get the agreement again: **Gawah-contract-v2.pdf**, "... version 2 ...", with its change history (22,000 to 24,000, agreed by voice on call 2), and a voice note. The Clerk's lane says "contract v2".

If one of you did not say haan, that person gets a call-back link instead: do step 8 for them.

---

## Day 7

### 14. The work is done

1. "Second phone" panel (Ramesh): send `kaam poora ho gaya`.
2. Phone: Gawah asks Sunita: 'Ramesh ji ne likha hai: "kaam poora ho gaya". ...' with **Haan, sahi hai** and **Nahi** buttons.
3. Phone: tap **Haan, sahi hai** (typing `haan` works too).

**You should see**: the "Second phone" panel gets `👍 (reaction)`; then both of you: "Kaam poora ho gaya, dono ne confirm kiya. Deal ke hisaab se baaki ₹19,000."

### 15. The reminder

Wait about a minute (the Sentinel's delay, `SENTINEL_BALANCE_REMINDER_SECONDS`, 60 by default; set it in the shell before step 1 to change it).

**You should see:**
- Phone: "Yaad dila raha hoon: kaam poora ho chuka hai, dono ne confirm kiya tha. Deal ke hisaab se ₹19,000 baaki hai."
- "Second phone" panel: "Gawah ne Sunita ji ko ₹19,000 baaki ki yaad dila di hai."

### 16. Stop

Ctrl-C in the runner's terminal. It stops the server and the tunnel, deletes any room this run opened, and prints `LiveKit rooms open now: none`. The run's database and server log stay in `runs/`.

---

## When the phone gets nothing

On Meta, the server log says why (`not sent to ***NNNN: meta http ... code ...`; the codes are in `tools/META-SETUP.md`): most often an expired token (190), or more than 24 hours since the phone last wrote (131047: send Gawah any message from it). On Twilio's trial every send to your phone is refused. Either way you can go on by copying your links by hand. `http://localhost:8000/dashboard/phone?number=<your number>` shows everything Gawah sent you; your links are also Ramesh's with `hirer` in place of `worker`:

- Call (day 1 and day 5): Ramesh's call link from the "Second phone" panel, with the ending `/worker` changed to `/hirer`.
- Call-back: the same, with Ramesh's call-back link.
- The agreement: Ramesh's PDF link in the "Second phone" panel works for 15 minutes.

To get a link onto the phone: WhatsApp it to yourself from the laptop, or AirDrop it.

## Walking it through without a person

```
uv run python tools/run_live.py            # in one terminal
uv run python tools/walkthrough.py         # in another: the whole story, simulated phones, headless browsers
uv run python tools/walkthrough.py --from call2   # retry from call 2 on the latest deal
uv run python tools/walkthrough.py --offline      # nothing outside: tests/offline.py in-process
```

It writes every event, each step with its time and result, and dashboard screenshots to `runs/walk-<time>/`.
