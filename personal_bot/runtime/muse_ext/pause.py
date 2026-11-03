"""Emergency configuration fence; deliberately never opens the database."""
import argparse
import json
from pathlib import Path
from brain import atomic_json, config_guard


def pause(root):
    root=Path(root)
    with config_guard(root):
        try:
            cfg=json.loads((root/'config.json').read_text(encoding='utf-8'))
            if not isinstance(cfg,dict):raise ValueError('invalid_config')
        except (ValueError,OSError):
            cfg={'version':'0.2.0','modules':{}}
        atomic_json(root/'state/pre-pause-config.json',cfg)
        epoch=cfg.get('epoch',0)
        cfg['enabled']=False
        cfg['epoch']=(epoch if type(epoch)==int and epoch>=0 else 0)+1
        cfg['features']={name:False for name in ('events','time_query','emotion_events','reminders','vector','consolidation','reading')}
        atomic_json(root/'config.json',cfg)
    return {'ok':True,'local_paused':True,'epoch':cfg['epoch'],'database_opened':False}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True)
    print(json.dumps(pause(p.parse_args().root)))
