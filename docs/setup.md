# Setup: from a fresh Ubuntu PC to running my tests

This is what I did, in order, on my machine (Ubuntu 24.04, RTX 3090). Where something went wrong, I say so and show the fix. A few commands are marked as "not run by me" — they're the official ones, but I didn't type them myself.

Rule I followed: **one step at a time.** Run a step, look at the output, then move on.

> Lines starting with `sudo` will ask for your password. Run those yourself in a normal terminal.

---

## 1. Check the GPU and driver

```bash
nvidia-smi
```

You want an RTX 3090 (or another 24 GB card) and a driver that supports CUDA 13 (HyperQwen asks for 580 or newer). Mine showed driver 595.99.02, CUDA 13.2.

## 2. Free up the GPU

HyperQwen needs almost the whole 24 GB. Look at the `Processes` list in `nvidia-smi`. If anything else is holding GPU memory (another AI service, for example), stop it first.

My PC also runs two of my own AI services, so I stopped them (stop, **not** disable):

```bash
sudo systemctl stop <your-service-names>
nvidia-smi
```

After this, only the desktop (`gnome-shell`, `Xwayland`) was left on the card, about 100 MiB.

> ⚠️ If those services start again at boot, they grab the memory first and HyperQwen keeps crashing and restarting. Mine restarted **511 times** before I noticed. See [issues.md](issues.md).

## 3. Make sure Docker can use the GPU

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

## 4. Install the Hugging Face command and log in

Logged-in downloads are much faster. Install `hf` and log in with the device code it shows you. The install line is the official one from [Hugging Face's guide](https://huggingface.co/docs/huggingface_hub/en/guides/cli) (not run by me exactly like this — I didn't note down which install I used):

```bash
curl -LsSf https://hf.co/cli/install.sh | bash -s -- --exclude-skill
hf auth login
hf auth list
```

## 5. Get the code

I keep everything inside one folder. This repo on the outside, HyperQwen's own code inside it as `upstream/`:

```bash
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/frozenfussion/HyperQwen
cd HyperQwen
git clone https://github.com/syv-ai/HyperQwen upstream
```

I tested HyperQwen at commit `6ab9bd05cb84b538a6595d634f3e337ac8a80856`. To use exactly that version (not run by me — it was simply the latest when I cloned): `git -C upstream checkout 6ab9bd05cb84b538a6595d634f3e337ac8a80856`.

## 6. Download the models (about 21 GB)

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

## 7. Settings file

```bash
cd ~/projects/HyperQwen/upstream
cp .env.example .env
make keygen
echo "HF_HUB_DISABLE_XET=1" >> .env
```

`make keygen` adds an API key to `.env`. Keep `.env` private. The last line stops the same download stall inside Docker (HyperQwen downloads one more ~1 GB piece on first start).

The default `.env` already selects the fast single-user mode (`SPEC=dflash2`, prefix cache on).

## 8. Start HyperQwen

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

## 9. Check your GPU isn't being held back

Do this before trusting any speed numbers. While a request is running, look at the clocks and the reason:

```bash
nvidia-smi -q -d PERFORMANCE,CLOCK
```

A healthy 3090 under load runs its graphics clock well above 1,000 MHz. Mine sat at 390–600 MHz, with **SW Power Cap** listed as the reason, at only ~187 W. If yours shows that, your numbers will look like mine. Details in [issues.md](issues.md).

## 10. Set the power limit

HyperQwen's own numbers are measured at 250 W. The stock limit on my card is 370 W.

```bash
sudo nvidia-smi -pl 370      # or 250
nvidia-smi --query-gpu=power.limit --format=csv
```

This resets when the PC restarts.

## 11. Run my tests

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

## 12. Stop it when you're done

```bash
cd ~/projects/HyperQwen/upstream
docker compose down
```

This keeps the image and the models on disk. `docker compose --profile single up -d` brings it back. If you stopped other GPU services in step 2, start them again.
