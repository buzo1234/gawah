# The real run, step by step

You play both people, alone, in a quiet room.

- **Your phone is Sunita**, the hirer. Real WhatsApp, and the call in the phone's browser.
- **The laptop is Ramesh**, the worker. His WhatsApp is the dashboard's "Second phone" panel. His call is the call link opened in the laptop's browser.

About 20 minutes. It uses about 30 LiveKit minutes and one of the dozen Sage2 calls a month, so do it once, properly.

## Before you start

- Earphones in the laptop. Phone volume all the way down: you will hear Gawah and "Ramesh" through the laptop's earphones. A phone loudspeaker would be picked up by the laptop's microphone and taken for Ramesh.
- Phone and laptop at opposite ends of the room, at least 3 metres apart. Speak each person's lines close to that person's device, at a normal voice. Each microphone hears the other person faintly; distance keeps it below what counts as speech.
- Phone: screen timeout set to 5 minutes or more. The phone mutes its microphone when the screen locks or the call page goes to the background (open item 13).
- Have a phone hotspot ready in case the laptop's network drops.
- WhatsApp sandbox membership lapses on 24 November. If Gawah never answers, send the sandbox join message (`join <code>`) again first.

## 1. Start everything (laptop)

```
uv run python tools/demo.py
```

**You should see** six lines marked `OK` (OpenAI, Sage2, LiveKit, Twilio, S3, Chrome), then a box with the dashboard address, the webhook address, and "What to do first".

**If not:**
- `S3 ... EXPIRED`: the AWS keys are temporary. Put new ones in `.env`, all three together, and start again.
- `LiveKit ... room(s) open`: an old room is still costing minutes. Delete it in the LiveKit dashboard, or Ctrl-C and start again (the runner deletes only rooms it opened).
- `WARN this laptop cannot find the public address yet`: wait one minute before opening any link on the laptop. Do not keep reloading: every failed try makes the laptop remember "not found" for another minute.
- Anything else `FAIL`: the reason is on the line. Fix it before going on.

## 2. Point Twilio at this run (laptop, Twilio console)

The address changes on every start.

1. Twilio console > Messaging > Try it out > Send a WhatsApp message > **Sandbox settings**.
2. "When a message comes in": paste the webhook address from the box (it ends in `/whatsapp/webhook`). Method `POST`. Save.

## 3. Open the dashboard (laptop)

Open `http://localhost:8000/dashboard`.

**You should see** an empty dashboard: "No deal yet".

## 4. Say hello (phone)

Send `hi` to the sandbox number on WhatsApp.

**You should see:**
- Dashboard, "Real phone" panel: your `hi`.
- Phone: within a few seconds, "Namaste, main Gawah hoon. Deal shuru karne ke liye doosre vyakti ka mobile number bhejiye."

**If the dashboard shows nothing:** the webhook address in Twilio is wrong or not saved. Check step 2. In Twilio's console, Monitor > Logs > Errors shows what Twilio got back.

**If the dashboard shows your `hi` but the phone gets no answer:** Twilio refused the send (error 21654, open item 1). The server log says `not sent to ***0265`. Gawah still works; you will copy links by hand (see "When the phone gets nothing" at the end). Go on.

## 5. Start the deal (phone)

Send Ramesh's number: exactly what is in the "Second phone" panel's Number box, with the `+91` (by default `+910000000002`). Without the `+91` that number does not start a deal (open item 35).

**You should see:**
- Dashboard: a new deal; the people panel shows you as the hirer.
- Phone: "Namaste! Gawah aapki deal ka gawah rahega. Call ke liye yeh link kholiye: https://..."
- "Second phone" panel: "Namaste! Sunita ji (...) aapke saath kaam ki deal pakki karna chahte hain ... link kholiye: https://.../worker"

## 6. Join the call from both

1. Laptop: click Ramesh's link in the "Second phone" panel. It opens in a new tab. Press the green **Judiye** button and allow the microphone.
2. Phone: tap your link in WhatsApp. Press the green **Judiye** button and allow the microphone. If the WhatsApp in-app browser blocks the microphone, open the link in Chrome instead (the ⋮ menu > Open in Chrome).

**You should see:**
- Both pages say you are connected.
- In the earphones, within about 5 seconds: Gawah says the call is being recorded and greets you both. **Do not start talking until it has finished**: talking over Gawah stops it mid-sentence.
- Dashboard: the call is on; Gawah's opening line appears in the conversation.

**If Gawah never speaks:** look in the server log for `Gawah has no voice on this call`. The call still works without the voice; go on.

## 7. Talk (both devices)

Speak each line close to its device. Wait a second after each line. Gawah needs pauses.

| Device | Say |
|---|---|
| Phone (Sunita) | Hello Ramesh ji, main Sunita bol rahi hoon. Mujhe apna two BHK flat paint karwana hai, Indirapuram mein. |
| Laptop (Ramesh) | Haan ji madam. Tractor Emulsion, do coat, material ke saath pachees hazaar lagega. |
| Phone | Pachees bahut zyada hai. Baees hazaar final karo, material aapka. |
| Laptop | Theek hai madam, baees hazaar final. |
| Laptop | Advance kitna doge? Material ke liye paanch hazaar pehle chahiye. |
| Phone | Paanch hazaar advance main kal GPay kar dungi. |
| Laptop | Ji, isi number pe kar dena. |
| Phone | Chalo theek hai. Kaam kab se start karoge? |
| Laptop | Agle somvaar se shuru, shukravaar tak finish. |

**Now stop. Both quiet.** You moved on to dates without saying when the balance is paid.

**You should hear**, within about 10 seconds: Gawah asks Sunita when the balance will be paid.

**You should see** on the dashboard: the transcript under each name, the checklist filling in (work, amount, advance, dates), and a card under "Why Gawah spoke": "They moved on and left a term unclear · Balance".

**If Gawah does not ask in 20 seconds,** go on anyway, and note it. The dashboard checklist shows what the brain heard.

Then answer. Say no figure here: in the dry run "balance seventeen thousand" was heard as "seventy thousand", taken as a second total, and Gawah lined up the wrong question.

| Device | Say |
|---|---|
| Phone | Baaki paisa kaam poora hone ke din de dungi. |
| Laptop | Haan theek hai. |

Wrap up. Make it plain that the call is ending, in a few short lines: Gawah reads the terms back only once it hears you wrapping up, and in the dry run one summary line was not enough.

| Device | Say |
|---|---|
| Phone | Chalo theek hai phir. Sab tay ho gaya. |
| Laptop | Ji madam, Somvaar subah nau baje aa jaunga. |
| Phone | Theek hai, Somvaar ko milte hain. Bye. |

**Stop again, for 15 seconds.** Nobody has said what happens if the work is late, so Gawah should ask that first. Answer:

| Device | Say |
|---|---|
| Laptop | Late hua to har din ka paanch sau kaat lena. |
| Phone | Theek hai. |

Then Gawah should read the terms back. Answer "haan" from both.

**If Gawah says nothing:** the wrap-up was not detected (it was not in the dry run either). The call-back in step 8 still reads every term to each of you.

Then press **Call chhodein** on both.

**Check the dashboard now:**
- If a line appears twice, once under each name, the far microphone heard you. Move the devices further apart next time.
- The transcript is in Devanagari and not exact: in the dry run "seventeen thousand" came out as "seventy thousand" and "Royale thoda costly" as nonsense. Look at the checklist values, not the words.

## 8. The call-back, one person at a time

About 3 seconds after you both leave, each person gets a call-back link.

1. Phone: tap the call-back link ("Gawah aapse akele mein deal ki sharten confirm karna chahta hai"). Press **Baat shuru karein**.
2. Gawah reads each agreed term, one at a time. After each, say **"haan, sahi hai"**. Two words are enough.
3. It ends by itself.

Then the same on the laptop: open Ramesh's call-back link from the "Second phone" panel.

At the end Gawah names any term never agreed on the call ("yeh cheezein tay nahi hui thi"). That is expected for anything you did not say.

**You should see:** after each call-back, the dashboard shows that person's terms as confirmed. About 2 to 3 minutes each.

**If Gawah keeps waiting:** say "haan" a little louder, closer to the device.

## 9. The contract

About 30 seconds after the second call-back ends.

**You should see:**
- Phone: "Aapki deal ka contract taiyaar hai. Neeche PDF aur awaaz mein summary hai.", then the PDF, then a voice note.
- "Second phone" panel: the same three.
- Dashboard: the contract is ready.

**If the line says "par uski file abhi nahi bhej paaye":** the contract was written but no link could be made for the PDF. Check the S3 line in step 1.

**If nothing comes in 2 minutes:** look in the server log for `CONTRACT NOT WRITTEN`. The reason follows.

## 10. A cash record

1. Phone: send `2000 cash diya`.
2. "Second phone" panel: Gawah asks Ramesh: 'Sunita ji ne likha hai: "2000 cash diya". Kya yeh sahi hai? Haan ya nahi likhiye.'
3. "Second phone" panel: type `haan` and send.

**You should see:** the phone gets 'Ramesh ji ne haan kaha ...' (or 'Kaam karne wale ne haan kaha'), and the dashboard ledger shows the cash as confirmed.

Optional, the backed record: send a payment screenshot from the phone. It is logged straight away and nobody is asked.

## 11. Stop

Ctrl-C in the runner's terminal. It stops the server and the tunnel and deletes any room this run opened, then prints `LiveKit rooms open now: none`.

The run's database and server log stay in `runs/`.

## When the phone gets nothing

If Twilio refuses every send to your phone, the dashboard still shows everything Gawah sent to Ramesh. Your links are the same with `hirer` in place of `worker`:

- Call: copy Ramesh's link from the "Second phone" panel, change the ending `/worker` to `/hirer`, and open it on the phone (send it to yourself, or type it).
- Call-back: the same, with Ramesh's call-back link.
- Contract: Ramesh's PDF link in the "Second phone" panel works for 15 minutes.
