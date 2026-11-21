# Ideas

Product ideas that are not being built now. Status is Parked, Picked, or Dropped. Newest at the bottom of each section.

## The product

| # | Idea | Why it is parked | Status |
|---|---|---|---|
| 1 | **Work history across deals.** The same person's deals linked together, so a worker carries a record from job to job ("finished five jobs, paid late on two"). A knowledge graph only pays off here. | Needs a person to be the same person across deals (today people are stored per deal), consent to share history, and care that it does not become a blacklist. | Parked |
| 2 | **Deals made in person.** Both people in one room with one phone on speaker. | Telling apart who is speaking on one microphone is its own problem. The build is remote deals only. | Parked |
| 3 | **Real phone calls instead of a browser link.** Gawah rings both people; no smartphone browser needed. This is the real product; the demo uses a link. | Needs a KYC-verified Indian telephony account. The Twilio trial has no number and could not be confirmed to call Indian mobiles. | Parked |
| 4 | **A real ringing phone for the no-reply follow-up.** When a WhatsApp message goes unanswered, the phone actually rings. | Needs a Twilio trial number and a verified phone. Today the follow-up is a second message with a call link. | Parked |
| 5 | **Judge in disputes.** When something goes wrong during the job, the Judge gives both sides its reading of the record. Advisory, not a ruling. | Extension in `idea.md`. The core Judge only asks about missing terms. | Parked |
| 6 | **Clip replay on a dispute.** When someone disputes a term on their call-back, Gawah plays them the moment of the call where it was said. | Marked as a stretch for the `mouth` stream. Best single demo moment if there is time. | Parked |
| 7 | **Voice forensics.** Defend against a cloned or AI voice on the call. | Gawah records on its own line, so the realistic risk is impersonation, which the phone number covers for now. | Parked |
| 8 | **Khatabook or a shared ledger.** Connect the record ledger to a ledger people already use, as proof in a dispute. | Unknown whether Khatabook has an open API. The event log is the ledger for now. | Parked |
| 9 | **Stronger identity.** An ID check, or a voice print, instead of phone number plus spoken name. | Phone number and each person saying their name on the recording is enough for the demo. | Parked |
| 10 | **Standard legal clauses in the contract.** Jurisdiction, arbitration, liability. | The contract states only what the two people agreed. Adding boilerplate is Gawah putting terms into the deal. A product decision with real consequences; needs a lawyer. | Parked |
| 11 | **Assisted filing.** When a deal goes wrong, generate the claim and evidence bundle for the wage claims authority or the consumer commission. | Layer 4 of the dispute design discussed early on. Far beyond the demo. | Parked |
| 12 | **Escalation to the principal employer.** On a building site, a notice to the builder when a contractor does not pay, since the builder is liable. | Only applies to site work under the labour codes, not to household deals. | Parked |
| 13 | **Appointment letter from a voice deal.** For employers the labour codes cover: the spoken agreement produces the written appointment letter the law now requires. | Gives contractors a legal reason to use Gawah. A different customer from the household story. | Parked |
| 14 | **More languages.** Beyond Hindi and Hinglish. | Demo is Hindi and Hinglish only. | Parked |

## The build

| # | Idea | Why it is parked | Status |
|---|---|---|---|
| 20 | **Meta's WhatsApp test number** instead of the Twilio sandbox. | The fallback if Twilio keeps refusing real sends. More setup. | Parked |
| 21 | **Amazon Transcribe for amounts.** It heard "seventeen thousand" correctly where every OpenAI model heard "seventy". | OpenAI was better overall. Could be a second opinion on figures only. | Parked |
| 22 | **A second, earlier wrap-up signal** for the Judge. A trial question fires two lines sooner but gave one false alarm. | Switched off. A day-2 tuning decision. | Parked |
| 23 | **Open questions that survive a restart.** WhatsApp's pending confirmations and their timers are held in memory. | Fine for a demo run without restarts. | Parked |
