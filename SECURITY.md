# Security policy

## Reporting a vulnerability

Please don't open a public issue for a security problem. Report it privately on GitHub instead:
**[Security → Report a vulnerability](https://github.com/laugiov/woodshed/security/advisories/new)**.

Include what you found, how to reproduce it, and what an attacker could do with it. You'll get an
answer within a week. Once a fix is out, the advisory is published with credit to you, unless you
prefer otherwise.

## Supported versions

woodshed is in alpha: only the latest commit on `main` gets fixes.

## What matters most

woodshed runs on your own computer, so the interesting surfaces are the ones that face other people:

- **The library server** (`woodshed app`): it listens on this computer only by default. With
  `--host` and `--allow-network`, anyone on the network can reach it, and with
  `--uploads-from-network` they can add songs. Anything that lets a device on the network read files
  outside the library, run code, or take over the band's playback without the page's token is a
  vulnerability.
- **The practice page**: it loads nothing from the internet, and its Content Security Policy only
  allows the page's own files. A song file, a lyrics file or a page folder that makes the page run
  script or reach the network is a vulnerability.
- **The files woodshed reads**: audio and video are decoded by ffmpeg or libsndfile, lyrics are plain
  text. A crafted file that makes woodshed write outside its output folder is a vulnerability.

The models (Demucs, beat_this, MMS) are downloaded from their publishers on first use; problems in
those models or in PyTorch belong to their own projects.
