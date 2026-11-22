# -*- coding: utf-8 -*-
import json, os, re, sys, time
import urllib.request, urllib.error

BASE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE, '1688_1041092037687')
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}

def sanitize(name):
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', '_', name).strip()
    return name or 'unnamed'

def download(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        print('skip  ', path)
        return True
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            if not data:
                raise ValueError('empty response')
            with open(path, 'wb') as f:
                f.write(data)
            print('ok    ', os.path.basename(path), len(data) // 1024, 'KB')
            return True
        except Exception as e:
            print('retry%d' % (attempt + 1), url, e)
            time.sleep(1.5)
    print('FAIL  ', url)
    return False

def ext_of(url):
    m = re.search(r'\.(jpg|jpeg|png|gif|webp)', url.lower())
    return '.' + m.group(1) if m else '.jpg'

def main():
    data = json.load(open(os.path.join(BASE, 'components.json'), encoding='utf-8'))
    comps = data['data']

    main_imgs, sku_imgs, title = [], [], ''
    for comp in comps.values():
        ct = comp.get('componentType', '')
        d = comp.get('data') or {}
        if ct == '@ali/cmod-od-wap-main-pic':
            main_imgs = d.get('offerImgList', [])
            sku_imgs = [(s.get('name', ''), s.get('imgUrl', '')) for s in d.get('skuImages', [])]
        elif ct == '@ali/cmod-od-wap-offer-title':
            title = d.get('title', '')

    detail_imgs = []
    desc_path = os.path.join(BASE, 'desc.html')
    if os.path.exists(desc_path):
        txt = open(desc_path, encoding='utf-8', errors='replace').read()
        m = re.search(r'var offer_details=(\{.*\});?\s*$', txt, re.S)
        if m:
            try:
                details = json.loads(m.group(1))
            except json.JSONDecodeError:
                details = json.loads(m.group(1).rstrip(';'))
            content = details.get('content', '')
            detail_imgs = re.findall(r'<img[^>]+src="([^"]+)"', content)

    print('title:', title)
    print('main:', len(main_imgs), 'sku:', len(sku_imgs), 'detail:', len(detail_imgs))

    dirs = {
        'main': os.path.join(OUT_DIR, '主图'),
        'sku': os.path.join(OUT_DIR, 'sku图'),
        'detail': os.path.join(OUT_DIR, '详情页图'),
    }
    for p in dirs.values():
        os.makedirs(p, exist_ok=True)

    total = fails = 0
    for i, url in enumerate(main_imgs, 1):
        total += 1
        if not download(url, os.path.join(dirs['main'], '主图_%02d%s' % (i, ext_of(url)))):
            fails += 1
    for i, (name, url) in enumerate(sku_imgs, 1):
        total += 1
        fn = 'SKU_%02d_%s%s' % (i, sanitize(name), ext_of(url))
        if not download(url, os.path.join(dirs['sku'], fn)):
            fails += 1
    for i, url in enumerate(detail_imgs, 1):
        total += 1
        if not download(url, os.path.join(dirs['detail'], '详情_%02d%s' % (i, ext_of(url)))):
            fails += 1

    meta = {
        'offerId': '1041092037687',
        'title': title,
        'sourceUrl': 'https://detail.1688.com/offer/1041092037687.html',
        'mainImages': main_imgs,
        'skuImages': [{'name': n, 'url': u} for n, u in sku_imgs],
        'detailImages': detail_imgs,
    }
    with open(os.path.join(OUT_DIR, 'info.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print('\ndone: %d total, %d failed' % (total, fails))

if __name__ == '__main__':
    main()
