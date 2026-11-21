# Presentation prompt for Claude Design

Paste everything below the line into Claude Design. Upload the files listed under "Assets" along with it.

---

Design a pitch deck for **Gawah** (गवाह, "witness"), a hackathon project. About 12 slides, for a 3-minute pitch followed by a live demo. The audience is hackathon judges: technical, sceptical, short on time.

## The one idea

India's economy runs on zubaan - the spoken word. Gawah gives that word a witness.

Gawah is an AI that joins the phone call where a deal is made, between a household and a worker, and stays until the last rupee is paid. It listens like a third person on the line, speaks up when something is left unclear, writes the agreement, and remembers every word, so that when someone later says "aapne 25 hazaar bola tha", Gawah plays back what was actually agreed, in their own voices.

## Story, slide by slide

1. **Title.** Gawah / गवाह. The tagline: "India's economy runs on zubaan. We give that word a witness."
2. **One year ago today.** On 21 November 2025, India's four new labour codes took effect: formal employers must now give written appointment letters. One year on, the law has told formal India to write it down. The deal between a household and a painter, a plumber, a cook - is still just spoken.
3. **Two people, one fear.** Sunita, a homeowner, once paid a contractor an advance and he vanished. Ramesh, a painter, once finished a job and was paid half. Today Sunita wants to hire Ramesh. Neither trusts the other, and each fears the same thing from the other side.
4. **The numbers.** Large, few, sourced in small print:
   - 8 to 9 in 10 Indian workers are informal (SBI Research, 2026).
   - 58% of even salaried employees have no written contract (Periodic Labour Force Survey).
   - In construction, 0.4% of workers had a written contract in a Delhi and Bengaluru survey (Population Council); 1.7% in an ILO study.
   - 1 in 5 construction workers were not always paid on time (same survey).
   - Over 1.14 lakh labour and industrial cases were pending in May 2026 (Newslaundry, from national court data).
5. **What Gawah does.** Four steps, one line each:
   - On the call: listens to both people, and when a term is skipped or two figures are said, asks - in a natural Hindi voice, at a pause, without taking sides.
   - After the call: confirms the terms with each person separately, by voice.
   - The agreement: a two-language work agreement (Hindi and English) and a voice summary for anyone who cannot read, sent on WhatsApp.
   - Through the job: payments and finished work logged on WhatsApp; reminders when something is due.
6. **Demo.** A full-bleed slide that says "Live" with the two-call story as three beats: Day 1, the deal. Day 5, the argument. Day 7, the balance.
7. **The showpiece: receipts mid-argument.** Use the dashboard screenshot of the contradiction. Caption: on a second call, Ramesh says the total was 25,000. Gawah: "21 November ki call mein 24,000 tay hua tha. Suniye." - and plays the original moment.
8. **Under the hood: a crew, not a bot.** Eight agents on one call, each with one job: Ears (hears each person), Scribe (turns words into facts), Memory (searches every fact), Judge (decides what needs saying), Floor (decides when to speak), Gawah (the voice and reasoning, acting only through tools), Clerk (the agreement and its changes), Sentinel (watches between calls). Show them as one diagram around the call, with the event bus as their shared blackboard.
9. **The fact layer.** Why not plain RAG: it returns mentions, not truth - it cannot tell an offer from an agreement. Why not a full knowledge graph: a deal has tens of facts, not thousands. What Gawah uses: a small versioned fact graph - every fact knows who said it, when, the audio clip, who confirmed it, and what it replaced - with vector search on the side, and a hash chain so no past fact can be quietly changed.
10. **Built and measured.** A grid of real numbers from the build:
    - Gawah answers a question about the deal 3.7 s after the person stops speaking, and acknowledges in 1.7 s.
    - A spoken claim becomes a fact 1.5 s after the line; a contradiction is raised 1.9 s after it.
    - Hinglish speech: 36 to 40 of 42 amounts, dates, and names transcribed right; "haan theek hai" and "pakka" right every time.
    - Room noise: 0 false interruptions in 12 minutes of noise and clicks.
    - 410 automated tests across eight streams.
    Then one honest line: tested on five calls it had never seen, our first rule-based Judge caught only 4 of 10 moments - which is why Gawah's judgement now comes from the fact graph. [Replace with the new score once the re-test is in.]
11. **What's next.** Real phone and WhatsApp calls (the demo uses a call link in the browser); voice notes as the everyday way in; deals made face to face; a worker's history that follows them from job to job.
12. **Close.** The tagline again, and one line: "Zubaan, with a witness."

## Tone and visual direction

- Warm, trustworthy, plain. This is about dignity and trust, not pity: no stock photos of labourers, no sad imagery. Use the product itself - the dashboard, the agreement, the voice - as the imagery.
- Bilingual touches: "गवाह" in Devanagari on the title; short Hinglish quotes in the story slides, as people actually speak ("Balance kab milega?", "aapne 25 bola tha").
- Type: a clean sans with a matching Devanagari face (for example Inter with Mukta, or Noto Sans with Noto Sans Devanagari).
- Colour: warm off-white paper, near-black ink, and the product's own two signal colours used sparingly - deep green for agreed and confirmed, red for a contradiction.
- One idea per slide, large type, few words. Numbers big. Sources in small grey type at the bottom of the slide.

## Rules

- Do not invent numbers, quotes, or logos. Use only the figures above, with their sources.
- Do not call Gawah a lawyer, and do not say its agreement is "legally binding" or "enforceable". Say it is a written record of a spoken agreement, confirmed by both people by voice.
- Do not use any real company's branding.

## Assets

Upload these from the project folder:
- `fixtures/dashboard-shots/crew/2-contradiction.png` - the contradiction on the second call (slide 7).
- `fixtures/dashboard-shots/crew/4-after-amendment.png` - after a change both people agreed to by voice.
- `fixtures/dashboard-shots/crew/1-mid-call-facts.png` - facts appearing during the first call.
- `fixtures/contract-sample/contract-page-1.png` and `contract-page-2.png` - the work agreement.
