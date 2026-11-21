| Source | Model | Setting | Script (run 1) | Script flips | Facts right | Short replies right | Meaning kept | Lines with invented words | Empty | Delay median / max (s) |
|---|---|---|---|---|---|---|---|---|---|---|
| batch | gpt-4o-mini-transcribe | hi | deva 3, other:arabic 19, other:cyrillic 1, other:hangul 1 | 1 | 30/42 / 33/42 | 1/3 / 1/3 | 13/24 / 17/24 | 10 / 8 | 0 | 0.85 / 1.75 |
| batch | gpt-4o-mini-transcribe | none | deva 3, other:arabic 19, other:cyrillic 1, other:hangul 1 | 1 | 32/42 / 31/42 | 1/3 / 1/3 | 17/24 / 16/24 | 5 / 14 | 0 | 0.84 / 1.68 |
| batch | gpt-4o-mini-transcribe | prompt | deva 14, other:arabic 7, roman 3 | 5 | 37/42 / 33/42 | 1/3 / 1/3 | 17/24 / 17/24 | 7 / 8 | 0 | 0.84 / 1.50 |
| batch | gpt-4o-transcribe | hi | deva 9, other:arabic 13, other:cjk 1, roman 1 | 3 | 21/42 / 19/42 | 2/3 / 2/3 | 11/24 / 10/24 | 9 / 0 | 0 | 0.92 / 11.02 |
| batch | gpt-4o-transcribe | none | deva 9, mix 1, other:arabic 13, roman 1 | 3 | 19/42 / 19/42 | 1/3 / 1/3 | 7/24 / 8/24 | 9 / 8 | 0 | 0.98 / 1.71 |
| batch | gpt-4o-transcribe | prompt | deva 22, roman 2 | 5 | 34/42 / 32/42 | 2/3 / 2/3 | 15/24 / 13/24 | 5 / 0 | 0 | 0.83 / 11.24 |
| batch | gpt-transcribe | hi | deva 24 | 0 | 34/42 / 31/42 | 2/3 / 2/3 | 17/24 / 16/24 | 7 / 8 | 0 | 0.83 / 2.08 |
| batch | gpt-transcribe | hi+en | deva 24 | 0 | 33/42 / 31/42 | 3/3 / 2/3 | 16/24 / 15/24 | 8 / 9 | 0 | 0.83 / 1.35 |
| batch | gpt-transcribe | hi+en+keywords | deva 22, mix 2 | 0 | 35/42 / 36/42 | 3/3 / 3/3 | 19/24 / 19/24 | 5 / 6 | 0 | 0.84 / 1.47 |
| batch | gpt-transcribe | hi+en+prompt | deva 23, mix 1 | 0 | 38/42 / 38/42 | 3/3 / 3/3 | 19/24 / 20/24 | 0 / 4 | 0 | 0.83 / 1.17 |
| batch | gpt-transcribe | none | deva 21, mix 1, other:arabic 1, other:hangul 1 | 0 | 30/42 / 31/42 | 1/3 / 1/3 | 14/24 / 15/24 | 12 / 9 | 0 | 0.84 / 1.59 |
| batch | gpt-transcribe | prompt | deva 23, mix 1 | 0 | 40/42 / 38/42 | 3/3 / 3/3 | 21/24 / 20/24 | 3 / 4 | 0 | 0.82 / 1.33 |
| batch | whisper-1 | hi | deva 23, mix 1 | 0 | 30/42 / 31/42 | 2/3 / 2/3 | 17/24 / 18/24 | 8 / 0 | 0 | 2.10 / 9.37 |
| batch | whisper-1 | none | deva 18, mix 2, other:arabic 2, other:cyrillic 1, roman 1 | 1 | 32/42 / 31/42 | 1/3 / 1/3 | 17/24 / 16/24 | 6 / 1 | 0 | 2.08 / 10.06 |
| batch | whisper-1 | prompt | deva 9, empty 1, mix 1, other:arabic 6, roman 7 | 2 | 23/42 / 27/42 | 1/3 / 1/3 | 14/24 / 13/24 | 6 / 10 | 2 | 2.10 / 7.96 |
| batch-webm | gpt-transcribe | hi+en+prompt | deva 23, mix 1 | 0 | 34/42 / 36/42 | 3/3 / 3/3 | 19/24 / 20/24 | 5 / 4 | 0 | 0.81 / 1.48 |
| batch-webm | gpt-transcribe | prompt | deva 23, mix 1 | 0 | 38/42 / 36/42 | 3/3 / 3/3 | 20/24 / 20/24 | 4 / 4 | 0 | 0.89 / 2.31 |
| stream | gpt-live-transcribe | hi+en | deva 19, mix 5 | - | 28/42 | 2/3 | 15/24 | 10 | 0 | 0.78 / 0.96 |
| stream | gpt-live-transcribe | hi+en+prompt | deva 18, mix 6 | - | 35/42 | 3/3 | 17/24 | 6 | 0 | 0.80 / 1.00 |
| stream | gpt-live-transcribe | hi+en,delay-xhigh | deva 20, mix 4 | - | 28/42 | 3/3 | 16/24 | 8 | 0 | 0.79 / 0.96 |
| stream | gpt-realtime-whisper | none | deva 12, mix 3, other:arabic 5, other:bengali 1, other:hangul 2, other:hiragana 1 | - | 26/42 | 3/3 | 12/24 | 12 | 0 | 0.75 / 0.87 |
| stream | gpt-transcribe | hi+en | deva 24 | - | 31/42 | 3/3 | 17/24 | 8 | 0 | 0.82 / 1.31 |
| stream | gpt-transcribe | hi+en+prompt | deva 23, mix 1 | - | 37/42 | 3/3 | 19/24 | 5 | 0 | 0.83 / 1.01 |
| stream | gpt-transcribe | hi+en+prompt,server_vad | deva 24 | - | 32/42 | 3/3 | 20/24 | 7 | 0 | 1.05 / 1.68 |
| stream | gpt-transcribe | hi+en+prompt,server_vad-700 | deva 23, mix 1 | - | 34/42 | 3/3 | 19/24 | 6 | 0 | 1.55 / 1.78 |
| stream | gpt-transcribe | prompt | deva 23, mix 1 | - | 36/42 | 3/3 | 20/24 | 4 | 0 | 0.80 / 1.13 |
