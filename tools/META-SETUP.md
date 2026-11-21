# WhatsApp on Meta's Cloud API: setup and one live check

Gawah sends WhatsApp through Twilio's sandbox unless `.env` says `WHATSAPP_PROVIDER=meta`. Twilio's trial does not deliver to a real phone. Meta's free test number does, to up to five phones you verify.

With Meta, Gawah:

- asks every yes-or-no question with two reply buttons, "Haan, sahi hai" and "Nahi". Typing haan or nahi still works.
- puts call and call-back links in a button.
- reacts ✅ to a payment screenshot it logs as backed, and 👍 to a record once the other person confirms it.
- sends the contract as a PDF with a caption, and the spoken summary as a voice note.
- shows your message as read, and "typing…" while it works.

## What it costs, and Meta's rules

- **The 24-hour window.** Gawah can only message a phone within 24 hours of that phone's last message to it. Outside the window Meta refuses with error 131047, and the server log says so. The first message to someone who has never written to Gawah needs a template that Meta has approved, and Gawah does not use templates yet. **So each real phone sends Gawah a message first**, for example `hi`.
- **Free allowance.** Replies inside the window are free for the first 1,000 a month per number. Since 1 October 2026 Meta charges for every reply after that. One demo run sends about 30.
- **Test number.** It sends only to numbers on its list of allowed recipients. Meta's guides say up to five.
- **Pacing.** Meta allows 80 messages a second. To any one person it allows about one message every 6 seconds, with short bursts, and error 131056 means too fast. Gawah sends one message at a time, at least a second apart, so they arrive in order. The Twilio sandbox needed 3 seconds.
- **Access token.** The temporary token on the API Setup page lasts only a few hours. Make a fresh one before each session, or use a System User token, which does not expire (step 1.5).
- **The second phone.** The dashboard's "Second phone" panel works as it does on Twilio. Nothing sent to a simulated number reaches Meta. With Meta, the panel shows the buttons as `[Haan, sahi hai]  [Nahi]` under the question, and a reaction as `👍 (reaction)`.

## 1. On Meta's side (once)

You do this yourself, signed in to your own Facebook account. Gawah never creates accounts.

1. Go to developers.facebook.com > My Apps > **Create app** and pick the WhatsApp use case ("Connect with customers through WhatsApp"). Let it create or attach a business portfolio.
2. Open **WhatsApp > API Setup** (in some apps, Use cases > Customize).
   - **From** shows the test number. Copy its **Phone number ID** (an ID, not the phone number).
   - **To**: click "Manage phone number list" and add your phone. WhatsApp sends it a code; enter the code. Add each real phone you will use. Its number must also be in `VERIFIED_NUMBERS`.
   - Click **Generate access token** and copy it.
   - To check the token and your phone: send the **hello_world** test message from this page. It should arrive on your phone. This has worked on the user's setup.
3. **App secret:** in the left menu, **App settings > Basic > App secret > Show**. Copy the secret.
4. **Switch the app to Live.** Meta's dashboard will not let you configure webhooks until the app is published, and Meta's docs say some webhooks are not sent in development mode. On **App settings > Basic**, fill in:
   - an app icon,
   - a category,
   - a contact email,
   - a **privacy policy URL**: a public page. Any page you control that says what Gawah keeps will do.

   Save, then turn the **App mode** switch at the top of the dashboard from Development to **Live**. For your own test number, no app review is expected, but that is not confirmed. If Meta asks for a review, stop and tell the team before submitting anything.
5. Optional, for a token that does not expire: business.facebook.com > Settings > Users > **System users** > Add (Admin).
   - Assign it your app with full control.
   - Click Generate token and choose your app.
   - Give it the permissions `whatsapp_business_messaging`, `whatsapp_business_management` and `business_management`.

## 2. In `.env`

```
WHATSAPP_PROVIDER=meta
META_WHATSAPP_TOKEN=<the access token>
META_PHONE_NUMBER_ID=<the Phone number ID>
META_VERIFY_TOKEN=<any string you make up, e.g. gawah-7f3k>
META_APP_SECRET=<the App secret, step 1.3>
VERIFIED_NUMBERS=+91XXXXXXXXXX            # your phone, as on the allowed list
```

With `META_APP_SECRET` set, Gawah checks Meta's signature on every webhook and refuses one that does not match. Leave it empty only to get a demo running while you find the secret. Gawah then takes webhooks unsigned, and logs `META_APP_SECRET IS NOT SET` at startup and on every webhook: anyone who learns the tunnel address could then post as a phone.

`META_GRAPH_VERSION` can stay empty, which means v27.0. To go back to Twilio, set `WHATSAPP_PROVIDER=twilio` or delete the line.

## 3. Start the server, then point Meta at it

The tunnel address changes every time the tunnel starts, so do 3b again after every restart.

a. Start the tunnel and the server in two terminals:

```
cloudflared tunnel --url http://localhost:8000          # prints https://<words>.trycloudflare.com
PUBLIC_BASE_URL=https://<words>.trycloudflare.com uv run uvicorn app.main:app --port 8000
```

(`uv run python tools/demo.py` also starts both. Its service check still tests Twilio and prints Twilio's instructions, so a Twilio `FAIL` there means nothing when you are on Meta.)

b. On Meta's dashboard, open **WhatsApp > Configuration > Webhook > Edit**:

- **Callback URL**: `https://<words>.trycloudflare.com/whatsapp/webhook`
- **Verify token**: the same string as `META_VERIFY_TOKEN`
- Click **Verify and save**. The server log shows `GET /whatsapp/webhook?hub.mode=subscribe... 200`. A 403 means the two verify tokens differ.
- Under **Webhook fields**, subscribe to **messages**.

## 4. One live check, about 10 minutes

It costs about 12 WhatsApp messages to your phone (all free, inside the window), 2 small OpenAI calls to read two records, and 2 S3 uploads. It opens no LiveKit room. Open `http://localhost:8000/dashboard` on the laptop. Each step names what you should see.

1. **Hello.** Send `hi` to the test number. Your message gets blue ticks, then "typing…", then "Namaste, main Gawah hoon…". The dashboard's Real phone panel shows both.
   - Nothing on the dashboard: the webhook is wrong, or not subscribed to `messages` (step 3b).
   - On the dashboard, but nothing on the phone: the server log has `not sent to ***NNNN: meta http … code …`, with the reason in brackets. Code 190 means the token has expired. Code 131030 means your number is not on the allowed list.
2. **A deal, with a link button.** Send the second phone's number, `+910000000002`. You get "Namaste! Gawah aapki deal ka gawah rahega…" with a **Call kholiye** button. Tapping it opens the call page. Do not press join: that opens a LiveKit room. The second phone panel gets its own link as text.
3. **A question with buttons.** In the dashboard's Second phone panel, send `kaam poora ho gaya`. Your phone gets "Kaam karne wale ne likha hai…" with **Haan, sahi hai** and **Nahi** buttons. Tap **Haan, sahi hai**. Your phone gets "Shukriya, aapka jawab likh liya." and "Kaam poora ho gaya, dono ne confirm kiya." The panel gets `👍 (reaction)` and the confirmation. Tap the button again: "Is sawaal ka jawab pehle hi likh liya hai."
4. **A reaction on your record.** From your phone, send `2000 cash diya`. In the panel, type `haan`. On your phone, a 👍 appears on your `2000 cash diya` message, then "… ne haan kaha …".
5. **The contract as a document and a voice note.** In a third terminal:

   ```
   uv run python -m tests.meta_contract_live
   ```

   This uploads the sample contract (2 S3 uploads) and publishes `contract.ready` for the newest deal. Your phone gets **Gawah-contract-v1.pdf** captioned "Aapki deal ka contract, version 1. Awaaz mein summary neeche hai.", then a voice note with a play button.
6. Optional, if you have a real UPI payment screenshot with a transaction id: send it. Gawah downloads it with the token, and the reader logs it as backed. A ✅ appears on your screenshot, then "Record mein likh liya: …".

Stop the server and the tunnel with Ctrl-C. Report how many messages Gawah sent: the dashboard shows each one.

## If something is wrong

| Server log says | Means |
|---|---|
| `meta http 401 code 190` | The token has expired. Make a new one (step 1.2) or use a System User token (step 1.5). |
| Meta's webhook settings are greyed out, or no message ever reaches the server | The app is still in Development mode. Switch it to Live (step 1.4). |
| `META_APP_SECRET IS NOT SET` | Webhooks are taken unsigned. Fine for a quick check; set the secret (step 1.3) before the demo. |
| `code 131047` (often as `not delivered`, a few seconds after the send) | More than 24 hours since that phone last wrote. Send Gawah any message from it first. |
| `code 131030` | That phone is not on the test number's allowed list (step 1.2). |
| `code 131056` | Too many messages to one person too fast. Wait a minute. |
| `403 bad signature` on `POST /whatsapp/webhook` | `META_APP_SECRET` is wrong, or belongs to another app. Copy it again from App settings > Basic > App secret > Show. |
| `message(s) from a person with no phone number skipped` | The person uses a WhatsApp username and hides their number. Gawah knows people only by phone number. |
