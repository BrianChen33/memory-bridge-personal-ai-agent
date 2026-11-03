"""Synthetic portable fixtures; no production profile or memory is imported."""
import json
from pathlib import Path

POLICY = {
    'timezone': 'Asia/Shanghai', 'quiet_start': '01:00', 'quiet_end': '07:00',
    'news_threshold': 70, 'news_weights': {'relevance': 60, 'utility': 25, 'novelty': 15},
    'inferred_relevance_penalty': .65, 'news_expiry_hours': 72,
}
INTERESTS = {'interests': [
    {'id': 'ai-tools', 'topic': 'AI工具', 'basis': 'confirmed', 'source': 'fixture:user'},
    {'id': 'tech-news', 'topic': '科技动态', 'basis': 'inferred', 'source': 'fixture:inference'},
]}


def write_interests(root):
    Path(root, 'interests.json').write_text(json.dumps(INTERESTS), encoding='utf-8')


def seed_legacy_policy(root):
    p = Path(root, 'proactive-policy.json')
    if not p.exists():
        p.write_text(json.dumps(POLICY), encoding='utf-8')

