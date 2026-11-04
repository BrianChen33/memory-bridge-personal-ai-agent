"""Current-only host entry. May replace a retired host emotion.py in-place.

Keeps the import path used by existing host code without retaining old rules.
The reusable kit's unupgraded-root compatibility store is not used here.
"""
from muse_ext.emotion_catalog import ASSESSMENT_VERSION, LABELS


def submit_assessment(brain,event_id,raw):
    from muse_ext.companion import assess
    return assess(brain,event_id,raw,lambda *_:{'status':'conflict'})


def observe_event(brain,event_id,assessment=None):
    return {'status':'missing'} if assessment is None else submit_assessment(brain,event_id,assessment)
