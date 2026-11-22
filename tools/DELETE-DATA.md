# Removing a deal's data when someone asks

Gawah's privacy policy says either person can send "delete my data" to Gawah on WhatsApp, and their deal's data will then be removed. Gawah also understands "mera data delete karo" and "data hata do". It answers in one line that the request is received. It deletes nothing itself, because deleting recordings and the database needs a person (docs/DEVELOPMENT.md, "Stop and ask"). Do these steps by hand, soon after the request.

## 1. Find the request

- **Server log:** `deal=<deal id> DATA DELETION ASKED by ***NNNN (<role>): remove by hand`
- **Dashboard:** a sentinel note "... asked for this deal's data to be deleted".

`deal=no-deal` means the person has no deal. Gawah still holds their WhatsApp messages, so do step 3, matching on the phone number instead of the deal id.

Ask the team before going on. Stop the server first: it writes to the database while it runs.

## 2. Files and S3

Replace `<deal>` with the deal id, and `<bucket>` with `S3_BUCKET` from `.env`.

| Where | What |
|---|---|
| `recordings/<deal>/` | the call recordings, one folder per call |
| S3 `recordings/<deal>/` | the same recordings |
| S3 `contracts/<deal>-v*.pdf` and `-v*.ogg` | each contract version and its spoken summary |
| `memory-cache/` beside the database | cached embeddings of what was said, one file for all deals. Delete it; it is rebuilt, at the cost of embedding calls again |

```
rm -r recordings/<deal>
aws s3 rm s3://<bucket>/recordings/<deal>/ --recursive
aws s3 rm s3://<bucket>/contracts/ --recursive --exclude "*" --include "<deal>-v*"
```

## 3. The database

The database is `DATABASE_PATH`, or `gawah.db` in the project folder; a run started with `tools/run_live.py` has its own under `runs/`. Copy it aside first and delete the copy when you are done.

```
sqlite3 <database> <<'SQL'
DELETE FROM events WHERE deal_id = '<deal>';
DELETE FROM deals WHERE id = '<deal>';
DELETE FROM people WHERE deal_id = '<deal>';
DELETE FROM transcript_lines WHERE deal_id = '<deal>';
DELETE FROM records WHERE deal_id = '<deal>';
-- WhatsApp messages from before the deal existed are logged as no-deal:
DELETE FROM events WHERE deal_id = 'no-deal' AND name = 'whatsapp.message'
  AND json_extract(payload, '$.phone') IN ('+91XXXXXXXXXX', '+91YYYYYYYYYY');
SQL
```

In the last statement, put both people's numbers, with `+91`.

Also remove the deal's entries from `<database>.sentinel.json`, the waiting and sent reminders. If it holds nothing else, delete the whole file.

## 4. Outside Gawah

- **WhatsApp:** the messages stay on both people's phones, and in the provider's logs (Meta or Twilio) for as long as the provider keeps them. Gawah cannot remove these.

Then tell the person on WhatsApp, in one line, that it is done. For example: "Aapki deal ka data hata diya gaya hai."
