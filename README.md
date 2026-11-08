[![I tried to unlock my RTX 3090, and tested HyperQwen instead](https://faysalaziz.com/api/media/file/hyperqwen-rtx3090-banner.png/)](https://faysalaziz.com/latest/unlock-rtx-3090-tested-hyperqwen-instead/)

**Read the full story on my website:** [I tried to unlock my RTX 3090. I ended up testing HyperQwen instead.](https://faysalaziz.com/latest/unlock-rtx-3090-tested-hyperqwen-instead/)

# HyperQwen on my RTX 3090: what actually happened

I read the claim that [HyperQwen](https://github.com/syv-ai/HyperQwen) runs Qwen3.8-27B on a single RTX 3090 at around **127 tokens per second** for normal chat, and **381 tokens per second** when the answer copies text from the prompt. I wanted to see it for myself. So I set it up on a PC at home, ran my own tests, and wrote down everything — including the parts that went wrong.

Short version: **it works, and the speed trick is real: about 2.5–3× faster than the same model without it, and over 10× when copying text. But my card never got anywhere near HyperQwen's published numbers.** My used RTX 3090 is being held back by its driver at about 187 W (half of its 370 W limit), and I have not fixed that yet. So read my numbers as "a capped card", not as a verdict on HyperQwen.

Everything here is reproducible, and it is all in this README: [Setup](#setup), [Results](#results) and [Problems I hit](#problems-i-hit). The same sections are also in [`docs/`](docs/) as separate files.

## The machine

| Part | What I used |
|---|---|
| GPU | Gigabyte GeForce RTX 3090, 24 GB (bought used), VBIOS 94.02.42.40.B7 |
| CPU / board | AMD Ryzen 5 5600GT, ASRock A520M/ac |
| RAM | 14.9 GiB (as Linux reports it) |
| PSU | around 850 W (from memory, not checked on the label), two separate PCIe 8-pin cables to the card |
| OS | Ubuntu 24.04.4 LTS, kernel 7.0.0-42 |
| NVIDIA driver | 595.99.02 (CUDA 13.2) |
| Docker | docker.io 29.1.3, docker-compose-v2 2.40.3, NVIDIA Container Toolkit 1.20.1-1 |
| HyperQwen | commit `6ab9bd05cb84b538a6595d634f3e337ac8a80856`, image `ghcr.io/syv-ai/hyperqwen:latest` (digest `sha256:f706b092aabb156c23fe98c312ba7912fb8dbc0c107d4f152382113e33762f1c`), vLLM 0.32.0 |
| Mode | After: single-user, DFlash2 speculative decoding, 7 draft tokens, prefix cache on, 65,536-token context. Before: the same with `SPEC=off` (no speculative decoding) |

## My results at a glance

**Before** = HyperQwen with its speed trick switched off. **After** = HyperQwen's normal fast mode. Same model, same card, same tests. Medians, in tokens per second.

| Test | Before | After | HyperQwen's own figure* |
|---|---:|---:|---:|
| Normal chat (any thinking level) | 18.4 | 47.6–53.6 | ~127–133 |
| 15 minutes non-stop | 18.4 | 48.7 | — |
| Copy a ~25,000-token document back out | 16.6 | 176.2 | 381 |
| Summarise the same document | 16.5 | 38.3 | ~67–72 |
| Image questions (4 photos) | 18.3–19.0 | 41.7–61.0 | — |

\* HyperQwen's figures are from their own RTX 3090 at 250 W, with no cap. My card was capped by its driver at about 187 W the whole time (see [Problems I hit](#problems-i-hit)), so I can't match those. My Before vs After is the fair comparison.

What I take from it:

- **HyperQwen's trick works, even on a half-power card.** About **2.5–3× faster** for normal chat and images, and **over 10× faster** when copying text.
- **Thinking level doesn't change the speed per token much.** It changes how many tokens the model writes.
- **It stayed cool and steady.** 15 minutes of non-stop work, never above 60 °C.
- **Image understanding is good on people and details, shaky on facts,** and right or wrong changes from run to run. Full scoring with the pictures is in [Results](#results).

## What's in this repo

| Path | What it is |
|---|---|
| [docs/setup.md](docs/setup.md) | The Setup section as its own file |
| [docs/results.md](docs/results.md) | The Results section as its own file |
| [docs/issues.md](docs/issues.md) | The Problems section as its own file |
| [trial-spec.md](trial-spec.md) | A prompt and spec for an AI agent to do the whole setup and tests for you, with my fixes built in |
| `tests/` | My test scripts (plain Python, no extra packages) |
| `images/` | The four test images |
| `results/` | Raw results: every request with timestamps, plus GPU power/temperature/clock logs |

## How I did this

I'm not a full-time developer. I planned and researched with Claude, and Codex did the hands-on work on the PC from the instructions Claude wrote. I ran every `sudo` command myself, one step at a time, and every number here comes from a logged run.

## Setup

This is what I did, in order, on my machine (Ubuntu 24.04, RTX 3090). Where something went wrong, I say so and show the fix. A few commands are marked as "not run by me" — they're the official ones, but I didn't type them myself.

Rule I followed: **one step at a time.** Run a step, look at the output, then move on.

> Lines starting with `sudo` will ask for your password. Run those yourself in a normal terminal.

---

### 1. Check the GPU and driver

```bash
nvidia-smi
```

You want an RTX 3090 (or another 24 GB card) and a driver that supports CUDA 13 (HyperQwen asks for 580 or newer). Mine showed driver 595.99.02, CUDA 13.2.

### 2. Free up the GPU

HyperQwen needs almost the whole 24 GB. Look at the `Processes` list in `nvidia-smi`. If anything else is holding GPU memory (another AI service, for example), stop it first.

My PC also runs two of my own AI services, so I stopped them (stop, **not** disable):

```bash
sudo systemctl stop <your-service-names>
nvidia-smi
```

After this, only the desktop (`gnome-shell`, `Xwayland`) was left on the card, about 100 MiB.

> ⚠️ If those services start again at boot, they grab the memory first and HyperQwen keeps crashing and restarting. Mine restarted **511 times** before I noticed. See [issues.md](#problems-i-hit).

### 3. Make sure Docker can use the GPU

Check what you have:

```bash
docker compose version
docker info | grep -i -A3 runtimes
```

If `docker compose` says *unknown command*, or `nvidia` is not in the runtimes list, you need the two installs below. On Ubuntu's own Docker package (`docker.io`), I needed both.

**a) Docker Compose (Ubuntu package):**

```bash
sudo apt-get update && sudo apt-get install -y docker-compose-v2
```

**b) NVIDIA Container Toolkit** (from [NVIDIA's install guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)):

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
  && curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
```

```bash
sudo apt-get update && export NVIDIA_CONTAINER_TOOLKIT_VERSION=1.20.1-1 && sudo apt-get install -y \
  nvidia-container-toolkit=${NVIDIA_CONTAINER_TOOLKIT_VERSION} \
  nvidia-container-toolkit-base=${NVIDIA_CONTAINER_TOOLKIT_VERSION} \
  libnvidia-container-tools=${NVIDIA_CONTAINER_TOOLKIT_VERSION} \
  libnvidia-container1=${NVIDIA_CONTAINER_TOOLKIT_VERSION}
```

**c) Connect it to Docker and restart Docker.** Restarting Docker restarts your other containers too, so check with `docker ps` first.

```bash
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker && docker ps
```

### 4. Install the Hugging Face command and log in

Logged-in downloads are much faster. Install `hf` and log in with the device code it shows you. The install line is the official one from [Hugging Face's guide](https://huggingface.co/docs/huggingface_hub/en/guides/cli) (not run by me exactly like this — I didn't note down which install I used):

```bash
curl -LsSf https://hf.co/cli/install.sh | bash -s -- --exclude-skill
hf auth login
hf auth list
```

### 5. Get the code

I keep everything inside one folder. This repo on the outside, HyperQwen's own code inside it as `upstream/`:

```bash
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/frozenfussion/HyperQwen
cd HyperQwen
git clone https://github.com/syv-ai/HyperQwen upstream
```

I tested HyperQwen at commit `6ab9bd05cb84b538a6595d634f3e337ac8a80856`. To use exactly that version (not run by me — it was simply the latest when I cloned): `git -C upstream checkout 6ab9bd05cb84b538a6595d634f3e337ac8a80856`.

### 6. Download the models (about 21 GB)

Do this yourself with your logged-in `hf`, into `upstream/models`. HyperQwen finds them there and skips its own download.

> ⚠️ Hugging Face's newer download system ("Xet") stalled for me twice on the last file, crawling at 50–100 KB/s. Turning it off with `HF_HUB_DISABLE_XET=1` fixed it straight away, so I just use it from the start.

```bash
cd ~/projects/HyperQwen/upstream
HF_HUB_DISABLE_XET=1 hf download dbirks/Qwen3.8-27B-W4A16-AutoRound --local-dir models/Qwen3.8-27B-W4A16-AutoRound
```

You should see `Fetching 18 files: 100%`.

Then the small helper ("drafter") model. This is what I ran:

```bash
HF_HUB_DISABLE_XET=1 hf download syvai/Qwen3.8-27B-DFlash2-W4A16 --local-dir models/Qwen3.8-27B-DFlash2-W4A16 --include "*.json" "*.safetensors" "README.md"
```

> ⚠️ My `hf` version printed *"Ignoring `--include` since filenames have been explicitly set"* and fetched only `model.safetensors` and `README.md` — no settings file. So I fetched it separately:

```bash
HF_HUB_DISABLE_XET=1 hf download syvai/Qwen3.8-27B-DFlash2-W4A16 --local-dir models/Qwen3.8-27B-DFlash2-W4A16 --include "*.json"
ls -la models/Qwen3.8-27B-DFlash2-W4A16
```

### 7. Settings file

```bash
cd ~/projects/HyperQwen/upstream
cp .env.example .env
make keygen
echo "HF_HUB_DISABLE_XET=1" >> .env
```

`make keygen` adds an API key to `.env`. Keep `.env` private. The last line stops the same download stall inside Docker (HyperQwen downloads one more ~1 GB piece on first start).

The default `.env` already selects the fast single-user mode (`SPEC=dflash2`, prefix cache on).

### 8. Start HyperQwen

```bash
cd ~/projects/HyperQwen/upstream
docker compose --profile single up -d
docker compose logs -f single
```

The first start pulls a ~9.5 GB image, prepares the model and compiles kernels.

> ⚠️ For me the image download from GitHub's registry was painfully slow: about 1–1.5 MB/s on one 4.14 GB layer, while the same internet line did ~100 MB/s from Hugging Face. The whole first start took about **70 minutes**. Just leave it running.

When the logs settle, check it:

```bash
make doctor
```

You want `/health` to answer 200. Then a real request (this reads the key from `.env` without printing it):

```bash
KEY=$(grep '^VLLM_API_KEY=' .env | cut -d= -f2)
curl -s -H "Authorization: Bearer $KEY" http://127.0.0.1:18020/v1/models
```

It should list the model `qwen3.8-27b`.

> ℹ️ `make doctor` showed `SPEC=mtp` for me, which made me think the wrong mode was running. It wasn't — doctor reads your shell's settings, not `.env`. To see what the container really uses:
> `docker compose exec single env | grep -E '^(SPEC|CTX|PREFIX_CACHE|DFLASH_TOKENS)='`

### 9. Check your GPU isn't being held back

Do this before trusting any speed numbers. While a request is running, look at the clocks and the reason:

```bash
nvidia-smi -q -d PERFORMANCE,CLOCK
```

A healthy 3090 under load runs its graphics clock well above 1,000 MHz. Mine sat at 390–600 MHz, with **SW Power Cap** listed as the reason, at only ~187 W. If yours shows that, your numbers will look like mine. Details in [issues.md](#problems-i-hit).

### 10. Set the power limit

HyperQwen's own numbers are measured at 250 W. The stock limit on my card is 370 W.

```bash
sudo nvidia-smi -pl 370      # or 250
nvidia-smi --query-gpu=power.limit --format=csv
```

This resets when the PC restarts.

### 11. Run my tests

The scripts use only standard Python. They read the API key from `upstream/.env`, wait until the GPU is below 50 °C before each timed block, log GPU power/temperature/clocks every second, and save every request with timestamps to `results/`. They refuse to overwrite an existing block, so give each run a new `--block` name.

```bash
cd ~/projects/HyperQwen

# warm-up (not counted)
python3 tests/textbench.py --kind warmup --block my_warmup

# chat: 5 prompts x thinking off/low/medium/xhigh x 2 repeats
python3 tests/textbench.py --kind chat --block my_chat_370 --power 370

# 15 minutes non-stop
python3 tests/textbench.py --kind sustained --block my_sustained_370 --power 370
```

**Copy-the-document test.** First switch HyperQwen to its copy mode, then run:

```bash
cd ~/projects/HyperQwen/upstream
echo "DFLASH_TOKENS=15" >> .env
docker compose --profile single up -d --force-recreate
cd ..
python3 tests/textbench.py --kind copy-warmup --block my_copy_warmup --power 370
python3 tests/textbench.py --kind copy --block my_copy_370 --power 370
```

It uses `results/copy_document.txt` (about 25,000 tokens). Afterwards, remove the `DFLASH_TOKENS=15` line from `.env` and recreate again to go back to normal mode.

**Image test.** Switch images on, then run:

```bash
cd ~/projects/HyperQwen/upstream
echo "VISION=1" >> .env
docker compose --profile single up -d --force-recreate
cd ..
python3 tests/imagebench.py --kind warmup --block my_image_warmup
python3 tests/imagebench.py --kind measured --block my_images
```

With images on, mine needed about 5.5 minutes to become ready, and still had about 1.2 GB of GPU memory free.

**Before vs After.** To get the "Before" numbers, switch HyperQwen's speed trick off and run the same tests again with new block names. (The `sed` line is not run by me exactly like this — Codex changed that line in `.env` for me.)

```bash
cd ~/projects/HyperQwen/upstream
sed -i 's/^SPEC=dflash2/SPEC=off/' .env
docker compose --profile single up -d --force-recreate
docker compose exec single env | grep -E '^SPEC='
```

It should print `SPEC=off`. Run every test above with `off_` block names, for example `--block off_chat_370`. Afterwards, put `SPEC=dflash2` back and recreate again.

### 12. Stop it when you're done

```bash
cd ~/projects/HyperQwen/upstream
docker compose down
```

This keeps the image and the models on disk. `docker compose --profile single up -d` brings it back. If you stopped other GPU services in step 2, start them again.

## Results

All tests ran on 7–8 November 2026, on the machine listed in the [README](#the-machine).

> **Read this first.** My card was held back by its driver ("SW Power Cap") at about **187 W**, even though the limit was set to 370 W. The graphics clock sat around 390–615 MHz instead of 1,000+ MHz. Changing to two separate power cables didn't fix it. So these are the numbers of a **capped** RTX 3090. Because the card never went above ~187 W, I only tested at 370 W — a 250 W run would have given the same numbers. See [issues.md](#problems-i-hit).

Every number below is a median unless it says otherwise. "TTFT" is time to first token: how long you wait before the answer starts. Raw data for every single request is in [`results/`](results/).

---

### Before vs After

**Before** = HyperQwen with its speed trick switched off (`SPEC=off`, no speculative decoding). **After** = HyperQwen's normal fast mode (DFlash2). Everything else is identical: the same model, the same card, the same capped ~187 W, and the same prompts and settings. After ran on 7–8 November 2026, Before on 8 November 2026. Medians, in tokens per second.

| Test | Before | After | Faster by |
|---|---:|---:|---:|
| Chat, thinking off | 18.37 | 50.55 | 2.8× |
| Chat, thinking low | 18.37 | 53.58 | 2.9× |
| Chat, thinking medium | 18.36 | 47.57 | 2.6× |
| Chat, thinking xhigh | 18.36 | 52.03 | 2.8× |
| 15 minutes non-stop | 18.38 (36 answers) | 48.73 (105 answers) | 2.7× |
| Copy the document | 16.57 | 176.24 | **10.6×** |
| Summarise the document | 16.50 | 38.27 | 2.3× |
| Image: selfie (off / xhigh) | 19.04 / 18.41 | 44.99 / 41.66 | 2.4× / 2.3× |
| Image: portrait (off / xhigh) | 18.39 / 18.46 | 44.45 / 41.85 | 2.4× / 2.3× |
| Image: ID card (off / xhigh) | 18.45 / 18.45 | 48.37 / 50.45 | 2.6× / 2.7× |
| Image: worksheet (off / xhigh) | 18.34 / 18.27 | 60.98 / 44.41 | 3.3× / 2.4× |

GPU in both: about 186–187 W, 59–60 °C max, graphics clock 390–420 MHz. Zero failed requests in both.

**What it means:** without the trick, this card writes about 18 tokens a second no matter what you ask. HyperQwen's trick makes it about **2.5–3× faster** for normal work, and **over 10× faster** when the answer copies text it has already seen. That's on a card running at half power.

### 1. Chat (text only)

Five everyday prompts (explain a fridge to a 12-year-old, a Python palindrome function with tests, the 2008 financial crisis in five bullets, an English-to-Malay translation, a one-day workshop agenda). Each prompt × each thinking mode × 2 repeats. Max 4,096 tokens.

| Thinking mode | Requests | Speed (tok/s) median / min / max | TTFT (s) median / min / max |
|---|---:|---|---|
| off | 10 | **50.55** / 25.12 / 98.05 | 0.163 / 0.134 / 0.190 |
| low | 10 | **53.58** / 42.66 / 78.74 | 0.169 / 0.080 / 0.452 |
| medium | 10 | **47.57** / 40.33 / 82.21 | 0.162 / 0.140 / 0.343 |
| xhigh | 10 | **52.03** / 44.00 / 64.34 | 0.244 / 0.238 / 0.653 |

GPU during this block: started at 42 °C, max 60 °C, median 186.2 W, graphics clock 405 MHz, memory clock 9,501 MHz.

**What it means:** the thinking level hardly changes the speed. It changes how much the model writes before answering. (Before, with the trick off: 18.4 tok/s for every mode.)

### 2. Fifteen minutes non-stop

Same prompts on a loop, thinking off, max 1,024 tokens, one request after another for 900 seconds. 105 requests.

| | First 2 minutes | Last 2 minutes |
|---|---:|---:|
| Speed | 50.62 tok/s | 46.45 tok/s |
| Power | 187.20 W | 186.75 W |
| Temperature (median / max) | 57 / 58 °C | 59 / 59 °C |
| Graphics clock | 420 MHz | 390 MHz |

Overall median: **48.73 tok/s**, TTFT 0.150 s. It stayed steady and cool. (Before, with the trick off: 18.38 tok/s, only 36 answers in the same 15 minutes.)

### 3. Copy the document

This is where HyperQwen's trick shines. The model gets a ~25,000-token document (built from HyperQwen's own docs, [`results/copy_document.txt`](results/copy_document.txt)) and is asked to write out the first 60 lines word for word. Because the answer copies the input, almost every guess from the helper model is right. As a control, the same document is summarised in five bullet points. HyperQwen's copy mode (`DFLASH_TOKENS=15`), thinking off, temperature 0, 3 repeats each.

| Task | Speed (tok/s) median / min / max | TTFT (s) |
|---|---|---|
| Copy first 60 lines | **176.24** / 174.31 / 178.46 | 0.932 |
| Summarise (control) | **38.27** / 38.15 / 38.37 | 0.953 |

Copying was **about 4.6× faster** than summarising. With the trick off, both ran at the same speed (16.57 vs 16.50 tok/s) — so this whole gap is HyperQwen's doing.

Two honest notes:
- The TTFT under 1 second is because the document was already cached from a warm-up run. It is not how long it takes to read 25,000 tokens from scratch.
- All three copy answers hit the 2,048-token limit, so they were cut off. The speed figure is still valid.

### 4. Images

HyperQwen switched to image mode (`VISION=1`). Four photos, each with thinking off and xhigh, 2 repeats each, max 4,096 tokens. I wrote down the correct answers **before** running anything, and I never asked the model who anyone is.

#### Speed

| Image | Thinking | Speed (tok/s) median | TTFT (s) median | Prompt tokens |
|---|---|---:|---:|---:|
| Selfie at the gates | off | 44.99 | 2.000 | 1,202 |
| Selfie at the gates | xhigh | 41.66 | 1.780 | 1,242 |
| Portrait | off | 44.45 | 1.716 | 1,193 |
| Portrait | xhigh | 41.85 | 1.813 | 1,233 |
| ID card | off | 48.37 | 0.474 | 175 |
| ID card | xhigh | 50.45 | 0.417 | 215 |
| Maths worksheet | off | 60.98 | 4.102 | 2,079 |
| Maths worksheet | xhigh | 44.41 | 3.252 | 2,119 |

GPU: started at 49 °C, max 60 °C, median 186.9 W, graphics clock 405 MHz.

#### How it did

##### Image 1 — my wife and me at the palace gates

![Selfie at the palace gates](images/01_selfie_gates.jpg)

**Prompt:** *"Describe this photo in detail: the people, their clothing, the setting and anything notable in the background. Where do you think it was taken, and why?"*

**Correct answer:** two people taking a selfie in winter clothes, in front of black and gold gates with the UK royal coat of arms (lion and unicorn). This is Buckingham Palace in London.

**Result: people right, place wrong — every time.** It described both of us, the clothes, the scarf, the backpack strap and the gold coat of arms well. But it named the wrong place in all 4 runs: **Paris (Les Invalides)** twice, **Madrid (Royal Palace)** once and **Edinburgh (Holyroodhouse)** once. The Edinburgh run did recognise the UK royal coat of arms with its lion and unicorn, then picked the wrong palace. None said Buckingham Palace.

##### Image 2 — portrait

![Portrait](images/02_portrait.jpg)

**Prompt:** *"Describe this photo in detail: the person's appearance, clothing, accessories, makeup, pose, expression and background."*

**Result: excellent.** White headscarf, thin gold hoop earrings, black winged eyeliner, light green eyes, orange lipstick, finger on the chin in a thinking pose, navy top with white flowers, plain grey background. All correct. The only slip: it said her lips were "slightly parted".

##### Image 3 — ID card (a fake I made)

![ID card](images/03_id_card.jpg)

**Prompt:** *"Read every piece of text on this card exactly as written. Then say what kind of document it is and explain what the long number encodes, if you know the format."*

**Correct answer:** a Malaysian MyKad. Text: `KAD PENGENALAN MALAYSIA`, `MyKad`, `550106-12-5821`, `ROWAN SEBASTIAN ATKINSON`, `GDW KAMPUNG BAYANGAN`, `80000 KENINGAU`, `SABAH`, `WARGANEGARA KHUNSA`, `H`. In the number, `550106` is the date of birth (6 January 1955), `12` is the place-of-birth code for **Sabah**, and the last four digits are a serial number ([Wikipedia](https://en.wikipedia.org/wiki/Malaysian_identity_card)).

**Result: mixed.**
- With thinking **on** (best run), it copied every line of text perfectly, called the card a parody, and even noticed the birth date matches the pictured actor's real birthday. But it said code `12` is **Kuala Lumpur**. Wrong: it's Sabah.
- The other thinking-on run used up all 4,096 tokens and was cut off mid-answer.
- With thinking **off**, it didn't copy the text as asked. One run misread "KHUNSA" and invented the meaning "Indonesian Citizen", and said `12` is **Penang**. The other run gave a two-line answer.

##### Image 4 — a child's maths worksheet

![Maths worksheet](images/04_worksheet.jpg)

**Prompt:** *"This is a child's maths worksheet. List every printed sum you can read with its correct answer. Then describe what is handwritten, drawn or stuck on top of the worksheet."*

**Result: good maths, made-up marking, and thinking mode failed.**
- Thinking **off**: it recognised single-digit subtraction and listed 52–53 sums. I checked them with a script, and **every answer was correct**. Both runs noticed the stickers and scribbles (one also the stamps). But both runs invented tick-and-cross "grading marks" that aren't on the page, and some sticker descriptions were off.
- Thinking **xhigh**: both runs spent all 4,096 tokens thinking and **gave no answer at all**.

#### Right or wrong changes from run to run

I ran the same four images again with the trick off (the "Before" runs). The trick isn't supposed to change the answers, only the speed. But some answers came out differently:

- In one "Before" run it **got the palace right**: Buckingham Palace, London, because it recognised the UK royal coat of arms. The other Before runs said Paris and Madrid, and one ran out of tokens.
- In one "Before" run it said **code 12 = Sabah** (correct). Another called it a Selangor code (wrong).
- The worksheet sums were again all correct (50 and 54 listed, 0 wrong), the made-up tick marks came back, and thinking mode ran out of tokens again.

With only two tries per image, right or wrong is partly luck. Don't trust a single answer on facts.

#### What I take from the image tests

- Describing people and details: very good.
- Facts that need knowledge (which palace, what a code means): unreliable. It sounds confident even when it's wrong.
- Thinking mode needs a much bigger token allowance for hard images. 4,096 cut off 3 of the 8 thinking runs. That part of my test wasn't fair to the model.

### 5. What I didn't test

- **250 W vs 370 W:** pointless while the card is capped at ~187 W.
- **Video:** the model understands video, but HyperQwen doesn't document it. With only about 1.2 GB of GPU memory spare with images on, I expect it to run out of memory, so I skipped it.
- **Many users at once (batch mode):** I only care about one user.

## Problems I hit

In the order they happened. Some of these will save you hours.

### 1. Hugging Face download stalled on the last file

**What happened:** the main model download ran at about 100 MB/s, then stalled at 16.92 GiB on the last file, crawling at 50–100 KB/s. Turning on Hugging Face's high-performance mode (`HF_XET_HIGH_PERFORMANCE=1`) didn't help. It stalled again in the same place.

**Fix:** switch off their newer download system, Xet:

```bash
HF_HUB_DISABLE_XET=1 hf download ...
```

The last file finished straight away. I now put `HF_HUB_DISABLE_XET=1` in `upstream/.env` too, because HyperQwen downloads one more piece inside Docker on its first start. ([Hugging Face env variable docs](https://huggingface.co/docs/huggingface_hub/en/package_reference/environment_variables))

### 2. `hf download` ignored my file filter

**What happened:** `--include "*.json" "*.safetensors" "README.md"` printed *"Ignoring `--include` since filenames have been explicitly set"* and skipped the `.json` settings file.

**Fix:** a second download with just `--include "*.json"`. Always check the folder with `ls -la` afterwards.

### 3. Docker couldn't run HyperQwen at all

**What happened:** `docker compose` → *unknown command*. And Docker had no NVIDIA runtime, so no GPU access. Ubuntu's own Docker package (`docker.io`) comes without both.

**Fix:** install `docker-compose-v2` and the NVIDIA Container Toolkit, then restart Docker. Exact commands in [setup.md](#3-make-sure-docker-can-use-the-gpu).

### 4. The Docker image took over an hour to download

**What happened:** the ~9.5 GB image comes from GitHub's container registry. One 4.14 GB layer crawled at about 1–1.5 MB/s, at one point 269 KiB/s, while the same line had done up to 868 Mbps. The first start took about 70 minutes, almost all of it this download.

**What I did:** nothing. I just let it run. Others have reported slow `ghcr.io` pulls from some regions, caused by bad network routes to GitHub's download servers ([containerd issue #9846](https://github.com/containerd/containerd/issues/9846)). I can't say for sure that's what happened to me.

### 5. A scary-looking memory warning at startup

**What happened:**

```
expandable_segments: memory mapping failed with OOM on device 0 while trying to map 20971520 bytes (free: 15532032, total: 25290604544)
```

**Outcome:** startup carried on and the server worked fine. HyperQwen's own notes (gotcha 35) show this exact warning as a sign that memory is right at the limit. In their cases it only killed the server when less than about 400 MiB was left free after startup. Mine had about 1.2 GB free, and the warning came back on later restarts without causing trouble.

### 6. `make doctor` showed the wrong mode

**What happened:** doctor said `SPEC=mtp`, but I had `SPEC=dflash2` in `.env`.

**Outcome:** a false alarm. Doctor reads your shell's settings, not `.env`. Inside the container it was `dflash2` with 7 draft tokens, which I confirmed with `docker compose exec single env`.

### 7. My RTX 3090 is power-capped at ~187 W (not solved)

**What happened:** under load the card sat at 390–615 MHz instead of the usual 1,000+ MHz, and drew only about 187 W, half of its 370 W limit. `nvidia-smi -q -d PERFORMANCE` said the reason was **SW Power Cap**. No heat problem (under 60 °C), no hardware power brake, no locked clocks.

**What I tried:**
- **Power cables.** The card was bought used and came without cables, so I'd plugged both of its 8-pin sockets into **one split cable** that came with my old RTX 4070. Split cables are a known no-no for these cards ([Micro Center](https://microcenter.com/site/mc-news/article/psa-psu-power-cable-requirements.aspx)). I changed to **two separate cables**. **No change.** Still about 187 W.

**Still possible:**
- a fault in the card's own power sensing (it's a used card, and "exactly half" looks like the card thinks one of its two inputs is maxed out)
- the card's firmware
- a Linux driver quirk

Others have posted the same symptom on NVIDIA's forum with no confirmed fix ([1](https://forums.developer.nvidia.com/t/rtx-3090-not-utilizing-full-power-limited-by-sw-power-cap-under-full-load/275528), [2](https://forums.developer.nvidia.com/t/rtx-3090-not-using-full-power-sw-power-cap-listed-as-reason/276974)). I'll come back to this.

**Why it matters:** every speed number in this repo is from a card running at about half power.

### 8. 511 restarts after a reboot

**What happened:** after restarting the PC, my other AI services started at boot and took about 3.4 GB of GPU memory. HyperQwen is set to restart itself if it stops, so it kept failing for lack of memory and restarting. **511 times**, over a couple of hours, before I noticed.

**Fix:** stop the other GPU services. HyperQwen then started cleanly by itself. On a shared PC, either stop the other services first, or run `docker compose down` when you're not using HyperQwen.

### 9. Thinking mode ran out of tokens on hard images

**What happened:** with thinking at xhigh and a 4,096-token limit, 3 of the 8 image runs used up every token. Both worksheet runs gave **no answer at all**.

**Lesson:** give thinking mode a much bigger limit for hard images.

## Want to try it yourself? Use the trial spec

This didn't go smoothly. My first spec didn't get through in one go: we hit snag after snag, and a lot of it ended up as manual work, step by step. So if you try this, you'll likely hit some of the same roadblocks.

To save you from that, I designed a prompt and a spec with the help of Claude: [trial-spec.md](trial-spec.md). Copy it, replace the bits in `<ANGLE_BRACKETS>` with your own, and give it to whatever AI agent harness you like: Claude Code, Codex, OpenCode, DeepSeek's harness, anything. It has all my fixes built in. No guarantees, but it's likely to work properly, so you don't have to face the hurdles I did.

### The prompt

Paste this into your agent:

```
Read trial-spec.md in this folder fully before doing anything, and follow it exactly.
Work one step at a time. After every step, show me what you ran and what came back.
Stop and ask me whenever the spec says STOP, whenever something unexpected happens,
and whenever a command needs sudo — I will run sudo commands myself.
Never print or save my API keys or tokens.
```

### The spec

<details>
<summary>Click to open the full trial spec (also in <a href="trial-spec.md">trial-spec.md</a>)</summary>


### Fill these in first

| Placeholder | What to put | Example |
|---|---|---|
| `<PROJECT_DIR>` | Where everything lives | `~/projects/HyperQwen` |
| `<GPU_SERVICES>` | Other services using your GPU, or `none` | `my-ai-service` |
| `<POWER_LIMIT_W>` | GPU power limit to test at | `370` (stock 3090) or `250` (HyperQwen's reference) |

### Ground rules for the agent

1. Work only inside `<PROJECT_DIR>`, except for the exact commands below.
2. Never run `sudo` yourself. Show the human the exact command, then wait for them to confirm it's done.
3. Never print, log or commit an API key or token. Never commit `upstream/`, `.env` files or model files.
4. One step at a time. If anything fails or looks unexpected: **STOP**, show the exact command and full error, and wait. Don't improvise fixes.
5. Keep notes of every command and its result in `results/run-notes.md`.
6. Long steps (downloads, the first start) can take over an hour. Slow is not stuck. Check progress, don't restart.

### Step 1 — Check the machine (read-only)

```bash
nvidia-smi
docker compose version
docker info | grep -i -A3 runtimes
df -h ~
hf auth list
```

Report:
- the GPU name and memory
- the driver version (HyperQwen asks for 580 or newer)
- whether `docker compose` works
- whether `nvidia` is listed as a Docker runtime
- free disk space (you need at least 40 GB)
- whether `hf` is installed and logged in

**STOP.**

### Step 2 — Install what's missing (human runs these)

Only for the items Step 1 found missing.

**Docker Compose** (if `docker compose` is an unknown command, on Ubuntu's `docker.io`):

```bash
sudo apt-get update && sudo apt-get install -y docker-compose-v2
```

**NVIDIA Container Toolkit** (if `nvidia` isn't a Docker runtime). Human runs these one at a time, and the agent checks the output after each:

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
  && curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
```

```bash
sudo apt-get update && export NVIDIA_CONTAINER_TOOLKIT_VERSION=1.20.1-1 && sudo apt-get install -y \
  nvidia-container-toolkit=${NVIDIA_CONTAINER_TOOLKIT_VERSION} \
  nvidia-container-toolkit-base=${NVIDIA_CONTAINER_TOOLKIT_VERSION} \
  libnvidia-container-tools=${NVIDIA_CONTAINER_TOOLKIT_VERSION} \
  libnvidia-container1=${NVIDIA_CONTAINER_TOOLKIT_VERSION}
```

Before restarting Docker, run `docker ps` and tell the human which containers will restart.

```bash
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker && docker ps
```

**Hugging Face CLI** (if `hf` is missing or not logged in), from [Hugging Face's guide](https://huggingface.co/docs/huggingface_hub/en/guides/cli):

```bash
curl -LsSf https://hf.co/cli/install.sh | bash -s -- --exclude-skill
hf auth login
```

Re-run Step 1. **STOP.**

### Step 3 — Free the GPU (human runs this)

If `<GPU_SERVICES>` isn't `none`:

```bash
sudo systemctl stop <GPU_SERVICES>
nvidia-smi
```

Use **stop**, never disable. Confirm only the desktop is left on the GPU (about 100 MiB). **STOP.**

### Step 4 — Get the code

```bash
mkdir -p <PROJECT_DIR> && cd <PROJECT_DIR>
git clone https://github.com/frozenfussion/HyperQwen .
git clone https://github.com/syv-ai/HyperQwen upstream
git -C upstream rev-parse HEAD
```

Report the HyperQwen commit.

### Step 5 — Download the models (human runs these in a plain terminal, so they can watch)

Always switch off Hugging Face's Xet downloader. It stalled on the last file for me twice. Use **one pattern per command**, because a list of patterns was misread by `hf`.

```bash
cd <PROJECT_DIR>/upstream
HF_HUB_DISABLE_XET=1 hf download dbirks/Qwen3.8-27B-W4A16-AutoRound --local-dir models/Qwen3.8-27B-W4A16-AutoRound
HF_HUB_DISABLE_XET=1 hf download syvai/Qwen3.8-27B-DFlash2-W4A16 --local-dir models/Qwen3.8-27B-DFlash2-W4A16 --include "*.json"
HF_HUB_DISABLE_XET=1 hf download syvai/Qwen3.8-27B-DFlash2-W4A16 --local-dir models/Qwen3.8-27B-DFlash2-W4A16 --include "*.safetensors"
ls -la models/Qwen3.8-27B-W4A16-AutoRound models/Qwen3.8-27B-DFlash2-W4A16
```

> These three drafter-download lines with one pattern each are this spec's fix for what I hit. I didn't run them exactly like this myself; see [Problems I hit](#problems-i-hit).

Expect 18 files for the main model. The drafter folder must have `model.safetensors` **and** a `.json` file. **STOP.**

### Step 6 — Settings

```bash
cd <PROJECT_DIR>/upstream
cp .env.example .env
make keygen
echo "HF_HUB_DISABLE_XET=1" >> .env
grep -E '^(SPEC|PREFIX_CACHE|HF_HUB_DISABLE_XET)=' .env
```

Expect `SPEC=dflash2`, `PREFIX_CACHE=1` and `HF_HUB_DISABLE_XET=1`. Never print the `VLLM_API_KEY` line.

### Step 7 — First start (the long one)

```bash
cd <PROJECT_DIR>/upstream
docker compose --profile single up -d
```

The first start pulls a ~9.5 GB image, then prepares the model. For me the image pull alone took over an hour. Every few minutes, report progress (`docker compose logs --tail 20 single`) and the restart count:

```bash
docker inspect -f 'restarts={{.RestartCount}} health={{.State.Health.Status}}' upstream-single-1
```

- If the restart count keeps climbing: **STOP**. Something else is probably holding GPU memory; go back to Step 3.
- A startup log line with `expandable_segments: memory mapping failed with OOM` is a known warning. Note it and continue. Only STOP if the server never becomes healthy.

Wait until `health=healthy`.

### Step 8 — Check it really works

```bash
cd <PROJECT_DIR>/upstream
make doctor
docker compose exec single env | grep -E '^(SPEC|CTX|PREFIX_CACHE|DFLASH_TOKENS|VISION)='
nvidia-smi --query-gpu=memory.used,memory.free --format=csv
```

Then the ready check, reading the key without printing it:

```bash
KEY=$(grep '^VLLM_API_KEY=' .env | cut -d= -f2)
curl -s -H "Authorization: Bearer $KEY" http://127.0.0.1:18020/v1/models
```

Trust the container's `SPEC` value, not `make doctor`'s, which reads the shell. Expect the model `qwen3.8-27b`. **STOP.**

### Step 9 — Power check (human runs the sudo line)

```bash
sudo nvidia-smi -pl <POWER_LIMIT_W>
```

Then the agent sends one test request:

```bash
cd <PROJECT_DIR> && python3 tests/textbench.py --kind warmup --block check_warmup
```

While it's generating, capture `nvidia-smi -q -d PERFORMANCE,CLOCK` and report the graphics clock, power draw and active "Clocks Event Reasons".

If the clock stays under ~700 MHz with **SW Power Cap** active, well below the power limit, **STOP and warn the human**. The card is power-capped, as mine was, and the numbers won't be comparable to HyperQwen's.

### Step 10 — Tests: After (HyperQwen on)

Use new block names. The scripts refuse to overwrite.

```bash
cd <PROJECT_DIR>
python3 tests/textbench.py --kind chat --block my_chat --power <POWER_LIMIT_W>
python3 tests/textbench.py --kind sustained --block my_sustained --power <POWER_LIMIT_W>
```

**Copy test.** Switch to copy mode, wait until healthy, run it, then switch back:

```bash
cd <PROJECT_DIR>/upstream && echo "DFLASH_TOKENS=15" >> .env && docker compose --profile single up -d --force-recreate
cd <PROJECT_DIR> && python3 tests/textbench.py --kind copy-warmup --block my_copy_warmup --power <POWER_LIMIT_W>
cd <PROJECT_DIR> && python3 tests/textbench.py --kind copy --block my_copy --power <POWER_LIMIT_W>
```

Remove the `DFLASH_TOKENS=15` line from `upstream/.env` and recreate.

**Images.** Add `VISION=1` to `upstream/.env`, recreate, wait until healthy, then:

```bash
cd <PROJECT_DIR>
python3 tests/imagebench.py --kind warmup --block my_image_warmup
python3 tests/imagebench.py --kind measured --block my_images
```

Report a table of median, min and max tokens per second and TTFT for every block.

### Step 11 — Tests: Before (HyperQwen's trick off)

In `upstream/.env`, change `SPEC=dflash2` to `SPEC=off`. Remove `VISION=1` for the text tests. Recreate, and confirm `SPEC=off` inside the container. Repeat every Step 10 test with `off_` block names. Images go last, with `VISION=1` added back.

Afterwards, restore `SPEC=dflash2`, recreate, and confirm it's healthy.

Report a **Before vs After** table: the same tests side by side, plus the "faster by" ratio.

### Step 12 — Clean up (human runs the sudo lines)

```bash
cd <PROJECT_DIR>/upstream && docker compose down
sudo nvidia-smi -pl <your card's default limit>
sudo systemctl start <GPU_SERVICES>
```

`docker compose down` keeps the image and models on disk. Confirm the other services are running again.

</details>

## Credits

All the clever work is [syv-ai/HyperQwen](https://github.com/syv-ai/HyperQwen) and the Qwen team. I only tested it.
