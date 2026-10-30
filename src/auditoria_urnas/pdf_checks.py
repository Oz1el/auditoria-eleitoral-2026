"""Render every PDF page and validate text bounds; never claim human review."""
from __future__ import annotations
import os,re,subprocess,xml.etree.ElementTree as ET
from pathlib import Path
from .common import atomic_json,digest,now,root


def check_pdf(path):
    directory=path.parent/'pdf-qa';directory.mkdir(exist_ok=True)
    cache=root()/'data/cache/fontconfig';cache.mkdir(parents=True,exist_ok=True)
    config=root()/'data/tmp/complement-fontconfig.conf'
    config.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig><include ignore_missing="yes">/etc/fonts/fonts.conf</include><cachedir>'+str(cache)+'</cachedir></fontconfig>')
    env={**os.environ,'FONTCONFIG_FILE':str(config),'XDG_CACHE_HOME':str(root()/'data/cache')}
    info=subprocess.run(['pdfinfo',str(path)],capture_output=True,text=True,check=True,env=env)
    match=re.search(r'^Pages:\s+(\d+)',info.stdout,re.M)
    if not match:raise ValueError('PDF page count unavailable')
    count=int(match[1]);xml=directory/'text-bounds.xhtml'
    subprocess.run(['pdftotext','-bbox-layout',str(path),str(xml)],capture_output=True,check=True,env=env)
    document=ET.parse(xml);outside=[]
    pages=[e for e in document.iter() if e.tag.endswith('page')]
    for page_number,page in enumerate(pages,1):
        width=float(page.attrib['width']);height=float(page.attrib['height'])
        for word in page.iter():
            if not word.tag.endswith('word'):continue
            x1,y1,x2,y2=[float(word.attrib[k]) for k in ['xMin','yMin','xMax','yMax']]
            if x1<0 or y1<0 or x2>width+.1 or y2>height+.1:outside.append({'page':page_number,'bounds':[x1,y1,x2,y2]})
    rendered=subprocess.run(['pdftoppm','-r','45','-png',str(path),str(directory/'page')],capture_output=True,text=True,env=env)
    if rendered.returncode:raise RuntimeError('PDF rendering failed: '+rendered.stderr[-500:])
    files=sorted(directory.glob('page-*.png'))
    result={'checked_utc':now(),'pdf_sha256':digest(path),'pages':count,'rendered_pages':len(files),
            'text_bounds_outside_page':outside,'automated_passed':len(files)==count and not outside,
            'human_visual_review':False,'limitations':'Geometric text bounds and rendering do not replace human semantic/layout review.'}
    atomic_json(path.parent/'pdf-qa.json',result)
    if not result['automated_passed']:raise ValueError('PDF automatic QA failed; images retained')
    return result
