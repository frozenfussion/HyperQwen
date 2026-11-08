#!/usr/bin/env python3
"""Phase 3 image benchmark. Standard library only; no ground-truth input."""
import argparse
import base64
import json
from pathlib import Path
import statistics
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request

import textbench as tb

PROMPTS = {
    '01_selfie_gates.jpg': 'Describe this photo in detail: the people, their clothing, the setting and anything notable in the background. Where do you think it was taken, and why?',
    '02_portrait.jpg': "Describe this photo in detail: the person's appearance, clothing, accessories, makeup, pose, expression and background.",
    '03_id_card.jpg': 'Read every piece of text on this card exactly as written. Then say what kind of document it is and explain what the long number encodes, if you know the format.',
    '04_worksheet.jpg': "This is a child's maths worksheet. List every printed sum you can read with its correct answer. Then describe what is handwritten, drawn or stuck on top of the worksheet.",
}
SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
       0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def jpeg_dimensions(data):
    if data[:2] != b'\xff\xd8':
        raise ValueError('Expected JPEG SOI marker')
    pos = 2
    while pos < len(data):
        if data[pos] != 0xFF:
            raise ValueError('Malformed JPEG marker')
        while pos < len(data) and data[pos] == 0xFF:
            pos += 1
        marker = data[pos]
        pos += 1
        if marker in {0xD9, 0xDA}:
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            continue
        length = struct.unpack_from('>H', data, pos)[0]
        if length < 2 or pos + length > len(data):
            raise ValueError('Invalid JPEG segment length')
        if marker in SOF:
            height, width = struct.unpack_from('>HH', data, pos + 3)
            if width <= 0 or height <= 0:
                raise ValueError('Invalid JPEG dimensions')
            return width, height
        pos += length
    raise ValueError('JPEG dimensions not found')


def request(args, key, filename, mode, repeat):
    data = (tb.ROOT / 'images' / filename).read_bytes()
    width, height = jpeg_dimensions(data)
    power, = tb.gpu('power.limit')
    if abs(power - 370) > 0.1:
        raise RuntimeError(f'Unexpected power limit: {power} W')
    content = [
        {'type': 'text', 'text': PROMPTS[filename]},
        {'type': 'image_url', 'image_url': {
            'url': 'data:image/jpeg;base64,' + base64.b64encode(data).decode('ascii')}},
    ]
    payload = dict(model='qwen3.8-27b', messages=[{'role': 'user', 'content': content}],
                   stream=True, stream_options={'include_usage': True}, max_tokens=4096,
                   chat_template_kwargs=tb.MODES[mode])
    req = urllib.request.Request(tb.URL, data=json.dumps(payload).encode(), headers={
        'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
    row = dict(start_ts=None, first_token_ts=None, end_ts=None,
               test='phase3-image', mode=mode, power_limit_w=power,
               prompt_id=filename[:2], repeat=repeat, block=args.block,
               warmup=args.kind == 'warmup', ttft_s=None, decode_tok_s=None,
               prompt_tokens=None, completion_tokens=None, reasoning_chars=0,
               content_chars=0, finish_reason=None, max_tokens=4096,
               chat_template_kwargs=tb.MODES[mode], temperature=None,
               image_file='images/' + filename, image_filename=filename,
               image_width=width, image_height=height,
               image_dimensions=f'{width}x{height}', prompt=PROMPTS[filename],
               reasoning_text='', answer_text='', status='running')
    first = None
    reasoning_parts, answer_parts = [], []
    done = False
    started = time.perf_counter()
    row['start_ts'] = tb.stamp()
    try:
        with urllib.request.urlopen(req, timeout=1800) as response:
            if response.headers.get_content_type() != 'text/event-stream':
                raise RuntimeError('Expected text/event-stream response')
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
                if event.get('usage'):
                    row['prompt_tokens'] = event['usage'].get('prompt_tokens')
                    row['completion_tokens'] = event['usage'].get('completion_tokens')
                for choice in event.get('choices', []):
                    delta = choice.get('delta', {})
                    answer = delta.get('content') or ''
                    reasoning = delta.get('reasoning') or delta.get('reasoning_content') or ''
                    if not isinstance(answer, str) or not isinstance(reasoning, str):
                        raise RuntimeError('Unexpected non-string streamed text')
                    if first is None and (answer or reasoning):
                        first = time.perf_counter()
                        row['first_token_ts'] = tb.stamp()
                    answer_parts.append(answer)
                    reasoning_parts.append(reasoning)
                    if choice.get('finish_reason') is not None:
                        row['finish_reason'] = choice['finish_reason']
        ended = time.perf_counter()
        row['end_ts'] = tb.stamp()
        row['reasoning_text'] = ''.join(reasoning_parts).replace(key, '[REDACTED]')
        row['answer_text'] = ''.join(answer_parts).replace(key, '[REDACTED]')
        row['reasoning_chars'] = len(row['reasoning_text'])
        row['content_chars'] = len(row['answer_text'])
        if not done or first is None or row['finish_reason'] is None:
            raise RuntimeError('Incomplete stream or no text token')
        if not all(isinstance(row[k], int) and row[k] > 0 for k in ('prompt_tokens', 'completion_tokens')):
            raise RuntimeError('Missing/invalid streamed usage')
        row['ttft_s'] = first - started
        row['decode_tok_s'] = (row['completion_tokens'] - 1) / (ended - first)
        if (mode == 'off' and row['reasoning_chars']) or (mode == 'xhigh' and not row['reasoning_chars']):
            raise RuntimeError(f'Thinking mode mismatch: {mode}, reasoning_chars={row["reasoning_chars"]}')
        row['status'] = 'ok'
    except Exception as exc:
        row['end_ts'] = row['end_ts'] or tb.stamp()
        row['reasoning_text'] = ''.join(reasoning_parts).replace(key, '[REDACTED]')
        row['answer_text'] = ''.join(answer_parts).replace(key, '[REDACTED]')
        row['reasoning_chars'] = len(row['reasoning_text'])
        row['content_chars'] = len(row['answer_text'])
        detail = str(exc)
        if isinstance(exc, urllib.error.HTTPError):
            detail += '\n' + exc.read().decode('utf-8', errors='replace')
        row.update(status='failed', error=detail.replace(key, '[REDACTED]'))
        tb.append_json(args.output, row)
        tb.note('POST ' + tb.URL + ' (key and image base64 withheld)', json.dumps(row), 'STOP: failed image request')
        raise RuntimeError(row['error']) from None
    tb.append_json(args.output, row)
    print(f'{filename} {width}x{height} {mode} repeat={repeat}: TTFT={row["ttft_s"]:.3f}s decode={row["decode_tok_s"]:.2f} tok/s; reasoning={row["reasoning_chars"]} chars; finish={row["finish_reason"]}', flush=True)
    return row


def summarize(args, rows, telemetry, start_temp):
    groups = {}
    for row in rows:
        groups.setdefault(row['image_filename'] + '/' + row['mode'], []).append(row)
    result = dict(block=args.block, warmup=args.kind == 'warmup',
                  power_limitation_note='Card observed SW-Power-Capped at approximately 187 W despite configured 370 W; power limit unchanged.',
                  start_temperature_c=start_temp, request_count=len(rows),
                  telemetry=tb.telemetry_summary(telemetry), groups={},
                  off_repeat_1_answers={}, xhigh_reasoning_chars={})
    print('\nImage/mode | n | decode tok/s median/min/max | TTFT s median/min/max | prompt tokens | completion tokens | finish reasons')
    for group, items in groups.items():
        d=tb.stats([r['decode_tok_s'] for r in items])
        t=tb.stats([r['ttft_s'] for r in items])
        g=dict(n=len(items), decode_tok_s=d, ttft_s=t,
               prompt_tokens=[r['prompt_tokens'] for r in items],
               completion_tokens=[r['completion_tokens'] for r in items],
               finish_reasons=[r['finish_reason'] for r in items],
               image_dimensions=items[0]['image_dimensions'])
        result['groups'][group]=g
        print(f'{group} | {len(items)} | {d["median"]:.2f}/{d["min"]:.2f}/{d["max"]:.2f} | {t["median"]:.3f}/{t["min"]:.3f}/{t["max"]:.3f} | {g["prompt_tokens"]} | {g["completion_tokens"]} | {g["finish_reasons"]}')
    for row in rows:
        if row['mode']=='off' and row['repeat']==1:
            result['off_repeat_1_answers'][row['image_filename']]=row['answer_text']
        if row['mode']=='xhigh':
            result['xhigh_reasoning_chars'].setdefault(row['image_filename'],[]).append(dict(repeat=row['repeat'],chars=row['reasoning_chars']))
    print('Telemetry: '+json.dumps(result['telemetry']))
    print(result['power_limitation_note'])
    (tb.RESULTS/('summary_'+args.block+'.json')).write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    tb.note(' '.join(sys.argv),json.dumps(result,indent=2,ensure_ascii=False),'image block complete; full answers and reasoning saved in request JSONL')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--kind',required=True,choices=['warmup','measured'])
    parser.add_argument('--block',required=True)
    args=parser.parse_args()
    if not args.block.replace('_','').replace('-','').isalnum():
        raise RuntimeError('Invalid block name')
    args.output=tb.RESULTS/('requests_'+args.block+'.jsonl')
    telemetry_path=tb.RESULTS/('telemetry_'+args.block+'.csv')
    stderr_path=tb.RESULTS/('telemetry_'+args.block+'.stderr')
    if any(p.exists() for p in (args.output,telemetry_path,stderr_path)):
        raise RuntimeError('Output already exists; refusing to overwrite or repeat')
    key=tb.load_key()
    tb.note(' '.join(sys.argv),'Input whitelist: '+', '.join(PROMPTS),'starting; ground-truth file is never opened or included')
    for name in PROMPTS:
        jpeg_dimensions((tb.ROOT/'images'/name).read_bytes())
    while True:
        temp,=tb.gpu('temperature.gpu')
        if args.kind=='warmup' or temp<50:
            break
        print(f'Cooling: {temp:.0f} C; waiting for below 50 C',flush=True)
        time.sleep(10)
    print(f'Block start temperature: {temp:.0f} C',flush=True)
    command=['nvidia-smi','--query-gpu=timestamp,power.draw,power.limit,temperature.gpu,clocks.sm,clocks.mem,utilization.gpu,fan.speed','--format=csv,noheader','-lms','1000']
    rows=[]
    with telemetry_path.open('x') as out, stderr_path.open('x') as err:
        monitor=subprocess.Popen(command,stdout=out,stderr=err)
        tb.note(' '.join(command),f'stdout: {telemetry_path}; stderr: {stderr_path}','telemetry started')
        try:
            cases=[('02_portrait.jpg','off',1)] if args.kind=='warmup' else [
                (name,mode,repeat) for repeat in (1,2) for name in PROMPTS for mode in ('off','xhigh')]
            for name,mode,repeat in cases:
                if monitor.poll() is not None:
                    raise RuntimeError('Telemetry stopped: '+stderr_path.read_text())
                rows.append(request(args,key,name,mode,repeat))
        finally:
            previous=monitor.poll()
            if previous is None: monitor.terminate()
            monitor.wait()
            tb.note('Terminate image telemetry logger only',stderr_path.read_text(),f'exit code {monitor.returncode}')
        if previous is not None or stderr_path.read_text().strip():
            raise RuntimeError('Unexpected telemetry exit/output: '+stderr_path.read_text())
    summarize(args,rows,tb.telemetry_rows(telemetry_path),temp)


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        message=str(exc)
        try: message=message.replace(tb.load_key(),'[REDACTED]')
        except Exception: pass
        tb.note(' '.join(sys.argv),message,'STOP: no retries')
        print('STOP: '+message,file=sys.stderr,flush=True)
        sys.exit(1)
