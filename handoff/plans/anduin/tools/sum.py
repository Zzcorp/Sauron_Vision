import sys, json
d = json.load(open(sys.argv[1]))
for k, v in d.items():
    if not isinstance(v, dict) or 'clipped' not in v:
        print(k, json.dumps(v)[:700]); continue
    if '1280' in k: continue
    print(k, '| under11', v['under11'], '| clipped', v['clipped'], '| overlaps', v['overlaps'], '| wide', v['wide'], '| lowC', v['lowContrast'], '| err', v.get('errors'), '|', v.get('metrics'), {a: (round(b, 1) if isinstance(b, float) else b) for a, b in v.get('perf', {}).items()})
