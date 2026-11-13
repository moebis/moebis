# moebis profile README

This repository is the public GitHub profile README for `moebis`.

## Rules

- Do not edit `README.md` or `assets/*.svg` by hand. They are generated.
- Edit `src/profile.json` (facts, card lines, buttons, links) or `src/portrait.txt`. Then run `python3 src/build.py`.
- Run `python3 src/build.py --check` before you commit. It fails when a generated file is out of date.
- Use only public facts that the owner approved. Do not add private infrastructure details, private contacts, age, job titles or invented metrics.
- Keep the profile static. Do not add tokens, scheduled jobs or GitHub Actions workflows.
- Do not use em dashes in user-facing text.
- The card is 52 columns wide on the right side. The build stops if a card line is too long.

## Portrait

- `src/portrait.txt` is the source of truth for the ASCII portrait. You can edit characters directly.
- To convert the original portrait image again, run `python3 src/build.py --photo PATH`. This step needs ImageMagick 7. The source image is not stored in this repository.
- The conversion is deterministic. Settings are in the `portrait` block of `src/profile.json`.
- After a portrait change, view both card themes at README size before you commit.
