# Trial spec: set up and test HyperQwen with an AI agent

This is the prompt and spec I built with Claude after doing the setup the hard way. Give it to an AI agent harness (Claude Code, Codex, OpenCode, DeepSeek's harness, or whatever you use) running on the PC with the GPU. It bakes in every fix from [Problems I hit](README.md#problems-i-hit).

**No guarantees.** Your machine is not my machine. But it should save you most of the roadblocks I hit.

Replace everything in `<ANGLE_BRACKETS>` before you use it.

---

## The prompt

Paste this into your agent:

```
Read trial-spec.md in this folder fully before doing anything, and follow it exactly.
Work one step at a time. After every step, show me what you ran and what came back.
Stop and ask me whenever the spec says STOP, whenever something unexpected happens,
and whenever a command needs sudo — I will run sudo commands myself.
Never print or save my API keys or tokens.
```

---

## The spec

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

> These three drafter-download lines with one pattern each are this spec's fix for what I hit. I didn't run them exactly like this myself; see [Problems I hit](README.md#problems-i-hit).

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
