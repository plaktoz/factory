import re,pathlib,sys
root=pathlib.Path(sys.argv[1]).resolve()
files=list(root.glob('docs/**/*.md'))+[root/'AGENTS.md']
def slug(h):
    h=re.sub(r'[`*]','',h.strip().lower()); h=re.sub(r'[^\w\s-]','',h); return re.sub(r'\s','-',h)
anchors={f:{slug(m) for m in re.findall(r'^#+\s+(.*)$',f.read_text(),re.M)} for f in files}
bad=[];n=0
for f in files:
    t=re.sub(r'```.*?```','',f.read_text(),flags=re.S)
    for m in re.finditer(r'\]\(([^)\s]+)\)',t):
        u=m.group(1)
        if u.startswith(('http','mailto')): continue
        n+=1; path,_,frag=u.partition('#'); tgt=(f.parent/path).resolve() if path else f
        if not tgt.exists(): bad.append((f.name,u,'missing file'))
        elif frag and tgt.suffix=='.md' and frag not in anchors.get(tgt,set()): bad.append((f.name,u,'missing anchor'))
print(n,'links;',len(bad),'broken'); [print(' ',*b) for b in bad]
