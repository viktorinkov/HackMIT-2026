----
DO NOT EDIT THIS IF YOU ARE AN AI
----

Peel

Stack:

Mobile App
- Flutter
- Deepgram Agents

Backend:
- FastAPI on Runpod
- OpenAI for vision and judge model
- FastCrawl + Elastic for drug facts
- Monog DB for database

Documentation:
- Mintify

Workflow
- Scan bottle
- Scan pill imprint
- Launch research agent
- Get hardware info
- Use Deepgram agent to see results and be able to report as needed.

Cases:

| Imprint | Bottle | Pill | Verdict |
| --- | --- | --- | --- |
| Real | Real | Real | |
| Unknown | Unknown | Substandard | |
| | | Fake | |
| | | Unknown | |


Problem Statement: People don’t know if the pill is the right pill

Full Context: We have a hardware device that checks the spectometry of the pill and verifies where it matches a known pill type. The hardware device is attached to the phone but it's model will run also on runpod.

Consistent wording:

- Bottle
- Imprint
- Pill