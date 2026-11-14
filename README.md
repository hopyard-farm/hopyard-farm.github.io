# Hopyard Farm Website (`hopyardfarm.org`)

Static website for **[Hopyard Farm, LLC](https://hopyardfarm.org)** in Graton, Sonoma County, California.

---

## How to Update the Website

Every push to `main` triggers GitHub Actions (`.github/workflows/hugo.yaml`) to run `python3 build.py` and publish `./public` to **[hopyardfarm.org](https://hopyardfarm.org)** in ~25 seconds.

### 1. Edit "Get to Know Your Farmer" (`content/farmer.txt`)
Edit [`content/farmer.txt`](content/farmer.txt) (even directly in the GitHub web editor). Separate paragraphs with a blank line.

### 2. Edit Barnstand Hours, Photos, or Optional Store (`content/farm.toml`)
Edit [`content/farm.toml`](content/farm.toml) to update:
- `[barnstand]` — Hours, status badge, address, and directions note.
- `[[photos]]` — The 9 photos in the 3×3 *From the Farm* grid and their Instagram post links.
- `[store]` — Set `enabled = true` whenever you'd like to turn on a pre-order / online farmstand section.

---

## Preview Locally

Requires only standard Python 3 (built into macOS):

```bash
# Build static files into ./public
python3 build.py

# Build and start a local preview server at http://localhost:8080
python3 build.py --serve
```
