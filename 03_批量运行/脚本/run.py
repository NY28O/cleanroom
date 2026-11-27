import argparse, base64, concurrent.futures, json, os, pathlib, time, urllib.error, urllib.request, uuid, hashlib
import sys

root = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
from transparent_png import REQUEST_FIELDS, read_transparent

run = pathlib.Path(__file__).resolve().parent
model = 'gpt-image-2.6-sunburst-tokenhub'
raw = run/'raw'
logs = run/'requests'
raw.mkdir(exist_ok=True)
logs.mkdir(exist_ok=True)

def edit(row):
    name = row['file']
    png = raw/name
    if png.exists():
        try:
            read_transparent(png.read_bytes(), '已有模型返回')
            return True
        except (OSError, ValueError) as exc:
            print(name, 'technical_hold', exc, flush=True)
            return False
    source = (root/row['source']).read_bytes()
    if hashlib.sha256(source).hexdigest() != row['sha256']:
        raise ValueError('Source changed: '+name)
    try:
        read_transparent(source, '原图')
    except (OSError, ValueError) as exc:
        print(name, 'technical_hold', exc, flush=True)
        return False
    fields = dict(model=model,prompt=prompt,quality='low',size='1024x1024',**REQUEST_FIELDS)
    boundary = uuid.uuid4().hex
    chunks = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k,v in fields.items()]
    chunks += [f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\nContent-Type: image/png\r\n\r\n'.encode(),source,f'\r\n--{boundary}--\r\n'.encode()]
    for _ in range(3):
        prior = sorted(logs.glob(name+'.*.json'))
        if len(prior) >= 3: return False
        log = logs/(name+'.'+str(len(prior)+1)+'.json')
        request = urllib.request.Request(base+'/images/edits',data=b''.join(chunks),headers={'Authorization':'Bearer '+key,'Content-Type':'multipart/form-data; boundary='+boundary})
        record = dict(file=name, model=model,quality='low',size='1024x1024',attempt=len(prior)+1,started_at=time.strftime('%Y-%m-%d %H:%M:%S'),status='processing')
        record['settings'] = {k: v for k, v in fields.items() if k != 'prompt'}
        log.write_text(json.dumps(record),encoding='utf-8')
        start=time.monotonic()
        retry=False
        wait=5 if not prior else 15
        try:
            with urllib.request.urlopen(request,timeout=175) as response:
                record['http']=response.status
                record['request_id']=response.headers.get('x-request-id')
                payload=json.load(response)
            record['usage']=payload.get('usage')
            record['response_model']=payload.get('model')
            for k,v in payload.items():
                if k not in ('data','usage','model') and any(s in k.lower() for s in ('cost','billing','charge','price')):
                    record[k]=v
            image=base64.b64decode(payload['data'][0]['b64_json'],validate=True)
            if not image.startswith(b'\x89PNG\r\n\x1a\n'): raise ValueError('Response is not PNG')
            tmp=png.with_suffix('.tmp')
            tmp.write_bytes(image)
            tmp.replace(png)
            try:
                read_transparent(image, '模型返回')
            except (OSError, ValueError) as exc:
                record.update(status='technical_hold', error=str(exc))
            else:
                record['status']='generated'
        except urllib.error.HTTPError as exc:
            record.update(http=exc.code,status='failed',request_id=exc.headers.get('x-request-id'))
            msg=exc.read(16384).decode(errors='replace')
            record['error']=msg[:700].replace(key,'[redacted]')
            retry=exc.code in (408,429,500,502,503,504)
            delay=exc.headers.get('retry-after','')
            if delay.isdigit(): wait=max(wait,int(delay))
        except Exception as exc:
            record.update(status='failed',error=str(exc).replace(key,'[redacted]')[:700])
        finally:
            record['elapsed_seconds']=round(time.monotonic()-start,2)
            log.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        print(name,record['status'],record.get('http'),record.get('usage') or record.get('error',''),flush=True)
        if png.exists(): return record['status'] == 'generated'
        if not retry or record['attempt']>=3 or wait>60: return False
        time.sleep(wait)
    return False

parser=argparse.ArgumentParser()
parser.add_argument('--first-only',action='store_true')
args=parser.parse_args()
try:
    base = os.environ['OPENAI_BASE_URL'].rstrip('/')
    key = os.environ['OPENAI_API_KEY']
except KeyError:
    raise SystemExit('请先配置 OPENAI_BASE_URL 和 OPENAI_API_KEY。')
prompt_path = run/'prompt.txt'
if not prompt_path.exists():
    prompt_path = root/'01_规则与提示词'/'温暖家居_编辑提示词.txt'
prompt = prompt_path.read_text(encoding='utf-8')
candidate_path = run/'candidates.jsonl'
if not candidate_path.exists():
    raise SystemExit('缺少 candidates.jsonl，请先建立本批次候选清单。')
rows=[json.loads(line) for line in candidate_path.read_text(encoding='utf-8').splitlines()]
if args.first_only:
    raise SystemExit(0 if edit(rows[0]) else 1)
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    raise SystemExit(0 if all(list(pool.map(edit,rows))) else 1)

