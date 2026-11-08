# Problems I hit (and what I did)

In the order they happened. Some of these will save you hours.

## 1. Hugging Face download stalled on the last file

**What happened:** the main model download ran at about 100 MB/s, then stalled at 16.92 GiB on the last file, crawling at 50–100 KB/s. Turning on Hugging Face's high-performance mode (`HF_XET_HIGH_PERFORMANCE=1`) didn't help. It stalled again in the same place.

**Fix:** switch off their newer download system, Xet:

```bash
HF_HUB_DISABLE_XET=1 hf download ...
```

The last file finished straight away. I now put `HF_HUB_DISABLE_XET=1` in `upstream/.env` too, because HyperQwen downloads one more piece inside Docker on its first start. ([Hugging Face env variable docs](https://huggingface.co/docs/huggingface_hub/en/package_reference/environment_variables))

## 2. `hf download` ignored my file filter

**What happened:** `--include "*.json" "*.safetensors" "README.md"` printed *"Ignoring `--include` since filenames have been explicitly set"* and skipped the `.json` settings file.

**Fix:** a second download with just `--include "*.json"`. Always check the folder with `ls -la` afterwards.

## 3. Docker couldn't run HyperQwen at all

**What happened:** `docker compose` → *unknown command*. And Docker had no NVIDIA runtime, so no GPU access. Ubuntu's own Docker package (`docker.io`) comes without both.

**Fix:** install `docker-compose-v2` and the NVIDIA Container Toolkit, then restart Docker. Exact commands in [setup.md](setup.md#3-make-sure-docker-can-use-the-gpu).

## 4. The Docker image took over an hour to download

**What happened:** the ~9.5 GB image comes from GitHub's container registry. One 4.14 GB layer crawled at about 1–1.5 MB/s, at one point 269 KiB/s, while the same line had done up to 868 Mbps. The first start took about 70 minutes, almost all of it this download.

**What I did:** nothing. I just let it run. Others have reported slow `ghcr.io` pulls from some regions, caused by bad network routes to GitHub's download servers ([containerd issue #9846](https://github.com/containerd/containerd/issues/9846)). I can't say for sure that's what happened to me.

## 5. A scary-looking memory warning at startup

**What happened:**

```
expandable_segments: memory mapping failed with OOM on device 0 while trying to map 20971520 bytes (free: 15532032, total: 25290604544)
```

**Outcome:** startup carried on and the server worked fine. HyperQwen's own notes (gotcha 35) show this exact warning as a sign that memory is right at the limit. In their cases it only killed the server when less than about 400 MiB was left free after startup. Mine had about 1.2 GB free, and the warning came back on later restarts without causing trouble.

## 6. `make doctor` showed the wrong mode

**What happened:** doctor said `SPEC=mtp`, but I had `SPEC=dflash2` in `.env`.

**Outcome:** a false alarm. Doctor reads your shell's settings, not `.env`. Inside the container it was `dflash2` with 7 draft tokens, which I confirmed with `docker compose exec single env`.

## 7. My RTX 3090 is power-capped at ~187 W (not solved)

**What happened:** under load the card sat at 390–615 MHz instead of the usual 1,000+ MHz, and drew only about 187 W, half of its 370 W limit. `nvidia-smi -q -d PERFORMANCE` said the reason was **SW Power Cap**. No heat problem (under 60 °C), no hardware power brake, no locked clocks.

**What I tried:**
- **Power cables.** The card was bought used and came without cables, so I'd plugged both of its 8-pin sockets into **one split cable** that came with my old RTX 4070. Split cables are a known no-no for these cards ([Micro Center](https://microcenter.com/site/mc-news/article/psa-psu-power-cable-requirements.aspx)). I changed to **two separate cables**. **No change.** Still about 187 W.

**Still possible:**
- a fault in the card's own power sensing (it's a used card, and "exactly half" looks like the card thinks one of its two inputs is maxed out)
- the card's firmware
- a Linux driver quirk

Others have posted the same symptom on NVIDIA's forum with no confirmed fix ([1](https://forums.developer.nvidia.com/t/rtx-3090-not-utilizing-full-power-limited-by-sw-power-cap-under-full-load/275528), [2](https://forums.developer.nvidia.com/t/rtx-3090-not-using-full-power-sw-power-cap-listed-as-reason/276974)). I'll come back to this.

**Why it matters:** every speed number in this repo is from a card running at about half power.

## 8. 511 restarts after a reboot

**What happened:** after restarting the PC, my other AI services started at boot and took about 3.4 GB of GPU memory. HyperQwen is set to restart itself if it stops, so it kept failing for lack of memory and restarting. **511 times**, over a couple of hours, before I noticed.

**Fix:** stop the other GPU services. HyperQwen then started cleanly by itself. On a shared PC, either stop the other services first, or run `docker compose down` when you're not using HyperQwen.

## 9. Thinking mode ran out of tokens on hard images

**What happened:** with thinking at xhigh and a 4,096-token limit, 3 of the 8 image runs used up every token. Both worksheet runs gave **no answer at all**.

**Lesson:** give thinking mode a much bigger limit for hard images.
