import re,sys,pathlib,json
root=pathlib.Path(sys.argv[1])/'docs/design/modules'
mods={}
for f in sorted(root.glob('*.md')):
    key=f.name.split('-')[0].upper().lstrip('0')
    t=f.read_text()
    defs=set(re.findall(r'^\s*(?:async )?def (\w+)\(',t,re.M))|set(re.findall(r'^\s*class (\w+)',t,re.M))
    mods[key]=(f.name,t,defs)
# depends-on blocks
out=[]; checked=[]; unknown=[]
for key,(fn,t,defs) in mods.items():
    m=re.search(r'\*\*Depends on:\*\*(.*?)(?:\n- \*\*Writes|\n- \*\*Run)',t,re.S)
    if not m: out.append((key,'NO Depends-on block','')); continue
    block=m.group(1)
    for line in re.findall(r'(?:^|\n)\s*(?:- )?(\w+[A-Za-z]?)\s*:\s*([^\n]+)',block):
        up,names=line
        up=up.upper()
        up={'6A':'6','6B':'6'}.get(up,up)
        checked.append((key,up))
        if up not in mods: unknown.append((key,up)); continue
        for n in re.findall(r'`(\w+)`',names):
            if n not in mods[up][2]:
                out.append((key,f'depends on {up}.{n}',f'{up} defines no `{n}`'))
for o in out: print(*o,sep=' | ')
print('edges checked',len(checked),'unknown upstream',sorted(set(unknown)))
print('modules',list(mods)); 
for k,(fn,t,d) in mods.items(): print(k,len(d),'defs')
