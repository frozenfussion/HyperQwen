#!/usr/bin/env python3
"""HyperQwen text benchmarks. Standard library only; stop on any failed request."""
import argparse
import csv
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'results'
TZ = ZoneInfo('Asia/Kuala_Lumpur')
POWER_NOTE = 'Card observed SW-Power-Capped at approximately 187 W despite a 370 W configured limit. All 250 W blocks skipped by user decision; power limit unchanged.'
URL = 'http://127.0.0.1:18020/v1/chat/completions'
PROMPTS = [
    'Explain how a refrigerator works to a 12-year-old.',
    'Write a Python function that checks whether a string is a palindrome, with three unit tests.',
    'Summarise the main causes of the 2008 financial crisis in five bullet points.',
    "Translate into Malay: 'The meeting has been moved to Thursday at 3 pm. Please bring the quarterly report.'",
    'Plan a one-day workshop agenda on project management basics, with times.',
]
MODES = {
    'off': {'enable_thinking': False},
    **{m: {'enable_thinking': True, 'reasoning_effort': m}
       for m in ('low', 'medium', 'xhigh')},
}


def stamp():
    return datetime.now(TZ).isoformat(timespec='milliseconds')


def note(command, output, result):
    RESULTS.mkdir(exist_ok=True)
    with (RESULTS / 'run-notes.md').open('a') as f:
        f.write(f'\n## {stamp()}\nCommand: `{command}`\nOutput:\n```text\n{output}\n```\nResult: {result}\n')


def gpu(fields):
    command = ['nvidia-smi', '--query-gpu=' + fields, '--format=csv,noheader,nounits']
    p = subprocess.run(command, capture_output=True, text=True)
    note(' '.join(command), p.stdout + p.stderr, f'exit code {p.returncode}')
    if p.returncode:
        raise RuntimeError(p.stdout + p.stderr)
    lines = p.stdout.strip().splitlines()
    if len(lines) != 1:
        raise RuntimeError('Expected exactly one GPU: ' + p.stdout)
    return [float(x.strip()) for x in lines[0].split(',')]


def load_key():
    for line in (ROOT / 'upstream/.env').read_text().splitlines():
        if line.startswith('VLLM_API_KEY='):
            key = line.split('=', 1)[1].strip().strip('\"\'')
            if key:
                return key
    raise RuntimeError('API key missing from upstream/.env')


def append_json(path, data):
    with path.open('a') as f:
        f.write(json.dumps(data, ensure_ascii=False) + '\n')


def request(args, key, prompt, mode, prompt_id, repeat, test, warmup, max_tokens, temperature=None):
    power, = gpu('power.limit')
    if args.power is not None and abs(power - args.power) > 0.1:
        raise RuntimeError(f'Power limit {power} W differs from required {args.power} W')
    payload = dict(model=args.model, messages=[{'role': 'user', 'content': prompt}],
                   stream=True, stream_options={'include_usage': True},
                   chat_template_kwargs=MODES[mode], max_tokens=max_tokens)
    if temperature is not None:
        payload['temperature'] = temperature
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(), headers={
        'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    row = dict(start_ts=None, first_token_ts=None, end_ts=None, test=test,
               mode=mode, power_limit_w=power, prompt_id=prompt_id, repeat=repeat,
               warmup=warmup, block=args.block, ttft_s=None, decode_tok_s=None,
               prompt_tokens=None, completion_tokens=None, reasoning_chars=0,
               content_chars=0, finish_reason=None, max_tokens=max_tokens,
               chat_template_kwargs=MODES[mode], temperature=temperature,
               status='running')
    first = None
    started = time.perf_counter()
    row['start_ts'] = stamp()
    done = False
    try:
        with urllib.request.urlopen(req, timeout=1800) as response:
            if response.headers.get_content_type() != 'text/event-stream':
                raise RuntimeError('Unexpected response content type: ' + str(response.headers))
            for raw in response:
                line = raw.decode('utf-8').strip()
                if not line.startswith('data:'):
                    continue
                data = line[5:].strip()
                if data == '[DONE]':
                    done = True
                    break
                event = json.loads(data)
                if event.get('error'):
                    raise RuntimeError(json.dumps(event['error']))
                usage = event.get('usage')
                if usage:
                    row['prompt_tokens'] = usage.get('prompt_tokens')
                    row['completion_tokens'] = usage.get('completion_tokens')
                for choice in event.get('choices', []):
                    delta = choice.get('delta', {})
                    content = delta.get('content') or ''
                    reasoning = delta.get('reasoning') or delta.get('reasoning_content') or ''
                    if not isinstance(content, str) or not isinstance(reasoning, str):
                        raise RuntimeError('Unexpected non-string content/reasoning delta')
                    if first is None and (content or reasoning):
                        first = time.perf_counter()
                        row['first_token_ts'] = stamp()
                    row['content_chars'] += len(content)
                    row['reasoning_chars'] += len(reasoning)
                    if choice.get('finish_reason') is not None:
                        row['finish_reason'] = choice['finish_reason']
        ended = time.perf_counter()
        row['end_ts'] = stamp()
        if not done or first is None or row['finish_reason'] is None:
            raise RuntimeError('Incomplete SSE response or no text tokens')
        if not all(isinstance(row[k], int) and row[k] > 0 for k in ('prompt_tokens', 'completion_tokens')):
            raise RuntimeError('Missing or invalid streamed usage')
        row['ttft_s'] = first - started
        row['decode_tok_s'] = (row['completion_tokens'] - 1) / (ended - first)
        if (mode == 'off' and row['reasoning_chars'] != 0) or (mode != 'off' and row['reasoning_chars'] == 0):
            raise RuntimeError(f'Thinking mode validation failed: mode={mode}, reasoning_chars={row["reasoning_chars"]}')
        row['status'] = 'ok'
    except Exception as exc:
        row['end_ts'] = row['end_ts'] or stamp()
        detail = str(exc)
        if isinstance(exc, urllib.error.HTTPError):
            detail += '\n' + exc.read().decode('utf-8', errors='replace')
        row['status'] = 'failed'
        row['error'] = detail.replace(key, '[REDACTED]')
        append_json(args.output, row)
        note('POST ' + URL + ' (authorization withheld)', json.dumps(row), 'STOP: request failed')
        raise RuntimeError(row['error']) from None
    append_json(args.output, row)
    print(f'{test} {prompt_id} {mode} repeat={repeat}: TTFT={row["ttft_s"]:.3f}s decode={row["decode_tok_s"]:.2f} tok/s; reasoning={row["reasoning_chars"]} chars; finish={row["finish_reason"]}', flush=True)
    return row


def stats(values):
    return {'median': statistics.median(values), 'min': min(values), 'max': max(values)} if values else None


def telemetry_rows(path):
    rows = []
    with path.open() as f:
        for r in csv.reader(f):
            if not r:
                continue
            if len(r) != 8:
                raise RuntimeError('Malformed telemetry: ' + repr(r))
            # nvidia-smi timestamps use the host local timezone (Asia/Kuala_Lumpur).
            ts = datetime.strptime(r[0].strip(), '%Y/%m/%d %H:%M:%S.%f').replace(tzinfo=TZ)
            vals = [float(x.strip().split()[0]) for x in r[1:]]
            rows.append(dict(ts=ts.timestamp(), power=vals[0], limit=vals[1], temp=vals[2], sm=vals[3], mem=vals[4], util=vals[5], fan=vals[6]))
    return rows


def telemetry_summary(rows):
    if not rows:
        return None
    return dict(median_power_w=statistics.median(r['power'] for r in rows),
                max_temperature_c=max(r['temp'] for r in rows),
                median_temperature_c=statistics.median(r['temp'] for r in rows),
                median_sm_mhz=statistics.median(r['sm'] for r in rows),
                median_memory_mhz=statistics.median(r['mem'] for r in rows))


def summarize(args, rows, telemetry, start_temp):
    groups = {}
    for row in rows:
        if row['status'] == 'ok':
            groups.setdefault(row['test'] + '/' + row['mode'], []).append(row)
    result = dict(block=args.block, power_limitation_note=POWER_NOTE, start_temperature_c=start_temp, request_count=len(rows),
                  warmup=args.kind in ('warmup', 'copy-warmup', 'probe'),
                  telemetry=telemetry_summary(telemetry), groups={})
    print('\nTest/mode | n | decode tok/s median/min/max | TTFT s median/min/max')
    for group, items in groups.items():
        d = stats([r['decode_tok_s'] for r in items])
        t = stats([r['ttft_s'] for r in items])
        result['groups'][group] = dict(n=len(items), decode_tok_s=d, ttft_s=t)
        print(f'{group} | {len(items)} | {d["median"]:.2f}/{d["min"]:.2f}/{d["max"]:.2f} | {t["median"]:.3f}/{t["min"]:.3f}/{t["max"]:.3f}')
        if args.kind == 'copy':
            result['groups'][group]['ttft_repeat_1_s'] = [r['ttft_s'] for r in items if r['repeat'] == 1]
            result['groups'][group]['ttft_repeats_2_3_s'] = [r['ttft_s'] for r in items if r['repeat'] in (2, 3)]
    if args.kind == 'sustained' and rows:
        start = datetime.fromisoformat(rows[0]['start_ts']).timestamp()
        end = datetime.fromisoformat(rows[-1]['end_ts']).timestamp()
        result['duration_s'] = end - start
        result['windows'] = {}
        for label, lo, hi in [('first_2_minutes', start, start + 120), ('last_2_minutes', end - 120, end)]:
            selected = [r for r in rows if lo <= datetime.fromisoformat(r['start_ts']).timestamp() < hi]
            result['windows'][label] = dict(request_assignment='request start within window',
                n=len(selected), decode_tok_s=stats([r['decode_tok_s'] for r in selected]),
                telemetry=telemetry_summary([r for r in telemetry if lo <= r['ts'] < hi]))
    print('Telemetry: ' + json.dumps(result['telemetry']))
    print(POWER_NOTE)
    if 'windows' in result:
        print('Sustained windows: ' + json.dumps(result['windows'], indent=2))
    if args.kind == 'copy':
        print('Copy/control repeat TTFT: ' + json.dumps(result['groups'], indent=2))
    path = RESULTS / ('summary_' + args.block + '.json')
    path.write_text(json.dumps(result, indent=2) + '\n')
    note(' '.join(sys.argv), json.dumps(result, indent=2), 'block complete; warmups excluded from measured blocks')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--kind', required=True, choices=['warmup', 'chat', 'sustained', 'copy-warmup', 'copy', 'probe'])
    parser.add_argument('--block', required=True)
    parser.add_argument('--power', type=float)
    parser.add_argument('--model', default='qwen3.8-27b')
    args = parser.parse_args()
    if not args.block.replace('_', '').replace('-', '').isalnum():
        raise RuntimeError('Invalid block name')
    args.output = RESULTS / ('requests_' + args.block + '.jsonl')
    telemetry_path = RESULTS / ('telemetry_' + args.block + '.csv')
    if args.output.exists() or telemetry_path.exists():
        raise RuntimeError('Block output already exists; refusing to overwrite or repeat')
    key = load_key()
    note(' '.join(sys.argv), '', 'block starting')
    warmup = args.kind in ('warmup', 'copy-warmup', 'probe')
    start_temp = None
    if not warmup:
        while True:
            start_temp, = gpu('temperature.gpu')
            if start_temp < 50:
                break
            print(f'Cooling: {start_temp:.0f} C; waiting for below 50 C', flush=True)
            time.sleep(10)
    else:
        start_temp, = gpu('temperature.gpu')
    print(f'Block start temperature: {start_temp:.0f} C', flush=True)
    telemetry_command = ['nvidia-smi', '--query-gpu=timestamp,power.draw,power.limit,temperature.gpu,clocks.sm,clocks.mem,utilization.gpu,fan.speed', '--format=csv,noheader', '-lms', '1000']
    rows = []
    stderr_path = RESULTS / ('telemetry_' + args.block + '.stderr')
    with telemetry_path.open('x') as out, stderr_path.open('x') as err:
        monitor = subprocess.Popen(telemetry_command, stdout=out, stderr=err)
        note(' '.join(telemetry_command), f'stdout: {telemetry_path}; stderr: {stderr_path}', 'telemetry started')
        def send(prompt, mode, pid, repeat, test, limit, temp=None):
            if monitor.poll() is not None:
                raise RuntimeError('Telemetry process exited: ' + stderr_path.read_text())
            rows.append(request(args, key, prompt, mode, pid, repeat, test, warmup, limit, temp))
        try:
            if args.kind == 'warmup':
                for i, prompt in enumerate(PROMPTS, 1):
                    send(prompt, 'off', f'P{i}', 1, 'warmup', 4096)
            elif args.kind == 'chat':
                for repeat in (1, 2):
                    for i, prompt in enumerate(PROMPTS, 1):
                        for mode in MODES:
                            send(prompt, mode, f'P{i}', repeat, '2a-chat', 4096)
            elif args.kind == 'sustained':
                started = time.monotonic()
                i = 0
                while time.monotonic() - started < 900:
                    send(PROMPTS[i % 5], 'off', f'P{i % 5 + 1}', i // 5 + 1, '2c-sustained', 1024)
                    i += 1
            else:
                doc = (RESULTS / 'copy_document.txt').read_text()
                instructions = {
                    '2b-copy': 'Reproduce the first 60 lines of the document above exactly, verbatim, with no commentary.',
                    '2b-control': 'Summarise the document above in five bullet points.',
                }
                for test, instruction in instructions.items():
                    if warmup and test != '2b-copy':
                        continue
                    for repeat in ((1, 2, 3) if args.kind == 'copy' else (1,)):
                        send(doc + '\n\n' + instruction, 'off', 'document', repeat, test,
                             1 if args.kind == 'probe' else 2048, 0)
        finally:
            already_exited = monitor.poll()
            if already_exited is None:
                monitor.terminate()
            monitor.wait()
            note('Terminate telemetry logger only', stderr_path.read_text(), f'logger exit {monitor.returncode}')
        if already_exited is not None or stderr_path.read_text().strip():
            raise RuntimeError('Unexpected telemetry exit/output: ' + stderr_path.read_text())
    summarize(args, rows, telemetry_rows(telemetry_path), start_temp)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        message = str(exc)
        try:
            message = message.replace(load_key(), '[REDACTED]')
        except Exception:
            pass
        note(' '.join(sys.argv), message, 'STOP: failure or unexpected result; no retries')
        print('STOP: ' + message, file=sys.stderr, flush=True)
        sys.exit(1)
