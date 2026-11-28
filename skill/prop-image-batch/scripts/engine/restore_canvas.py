"""等比恢复到原画布：只重采样一次，输出使用原图透明轮廓。"""
import hashlib, io, json, re
from pathlib import Path
from PIL import Image, ImageChops
from .preflight import require_source_dir
from .transparent_png import read_transparent, validate_asset

def restore_one(batch, source, row):
    n=row['file']
    if not re.fullmatch(r'[0-9]+-[0-9]+\.png', n):
        raise ValueError('无效的原图文件名：'+n)
    src=(source/n).read_bytes(); raw=(batch/'raw'/n).read_bytes()
    sha=lambda v:hashlib.sha256(v).hexdigest()
    if sha(src)!=row['sha256']: raise ValueError('原图校验值不符：'+n)
    logs=[json.loads(f.read_text(encoding='utf8')) for f in (batch/'requests').glob(n+'.*.json')]
    record = next((r for r in logs if r.get("image_sha256") == sha(raw)), None)
    if record is None:
        raise ValueError("高清原稿与请求记录不符："+n)
    orig=read_transparent(src,'原图'); im=read_transparent(raw,'高清原稿')
    a=orig.getchannel('A'); b=im.getchannel('A')
    def box(v):return v.point([0]*128+[255]*128).getbbox()
    sb,rb=box(a),box(b)
    if not sb or not rb:raise ValueError('无法定位主体：'+n)
    l,t,r,bt=sb; x,y,u,v=rb
    k=min((r-l)/(u-x),(bt-t)/(v-y))
    dx=(l+r-k*(u+x))/2;dy=bt-k*v
    # The floating source window maps both axes with the same scale.
    w,h=orig.size
    import math
    win=(-dx/k,-dy/k,(w-dx)/k,(h-dy)/k)
    pl=max(0,math.ceil(-win[0]));pt=max(0,math.ceil(-win[1]))
    pr=max(0,math.ceil(win[2]-im.width));pb=max(0,math.ceil(win[3]-im.height))
    canvas=Image.new('RGBA',(im.width+pl+pr,im.height+pt+pb));canvas.paste(im,(pl,pt))
    area=(win[0]+pl,win[1]+pt,win[2]+pl,win[3]+pt)
    out=canvas.convert('RGBa').resize(orig.size,Image.Resampling.LANCZOS,box=area).convert('RGBA')
    before = out.getchannel('A')
    m = a.point([0]*128+[255]*128)
    n2 = before.point([0]*128+[255]*128)
    iou = ImageChops.darker(m,n2).histogram()[255] / ImageChops.lighter(m,n2).histogram()[255]
    aligned_diff = sum(ImageChops.difference(a,before).histogram()[1:])
    # RGB without generated coverage must not become black opaque pixels.
    out = Image.composite(out, orig, before)
    # Keep generated RGB while using the source silhouette as the final edge
    # and hole mask for the replacement asset.
    out.putalpha(a)
    buf=io.BytesIO();out.save(buf,'PNG');payload=buf.getvalue()
    target=batch/'恢复图'/n;target.parent.mkdir(exist_ok=True)
    if target.exists() and target.read_bytes()!=payload:raise ValueError('已有不同恢复稿，需另建版本：'+n)
    if not target.exists():target.write_bytes(payload)
    out=read_transparent(target.read_bytes(),'恢复稿');validate_asset(orig,out)
    a2=out.getchannel('A')
    diff=sum(ImageChops.difference(a,a2).histogram()[1:])
    return dict(file=n,raw_sha256=sha(raw),upload_size=record.get("upload_size"),requested_size=record.get("settings",{}).get("size"),raw_size=im.size,target_size=orig.size,exported_size=out.size,size_pass=True,transparent=True,scale=k,offset=[dx,dy],overlap=round(iou,4),aligned_alpha_different_pixels=aligned_diff,alpha_different_pixels=diff,alpha_equal=diff==0,output='恢复图/'+n,status='待验收' if diff==0 and iou>=.85 else '原尺寸通过；轮廓待复核')

def run_batch(batch, source, root):
    batch=Path(batch).resolve()
    if root/'03_批量运行' not in batch.parents:
        raise ValueError('请指定本仓库 03_批量运行 下的批次目录')
    rows=[json.loads(l) for l in (batch/'选样清单.jsonl').read_text(encoding='utf8').splitlines() if l.strip()]
    results=[restore_one(batch,source,r) for r in rows]
    (batch/'恢复核验.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
    return results
def main(root):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('batch',type=Path)
    parser.add_argument('--source-dir', required=True, help='启动检查使用的原图库目录路径')
    args=parser.parse_args()
    try:
        results=run_batch(args.batch, require_source_dir(args.source_dir), root)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'画布恢复未通过：{exc}\n')
    for row in results:print(row['file'],row['exported_size'],row['overlap'],row['alpha_different_pixels'])
